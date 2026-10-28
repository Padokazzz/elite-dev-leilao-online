from audit.services import pseudo
from django.db.models import Count, Sum
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuctioneer
from receipts.models import Receipt
from wallets.exceptions import HoldInconsistentError

from .models import Auction
from .pagination import AuctionPagination
from .serializers import AuctionCreateSerializer, AuctionScheduleSerializer
from .services import (
    CancelRejected,
    RescheduleRejected,
    cancel_auction,
    reschedule_auction,
    settle_if_expired,
)

CATALOG_STATUSES = {
    Auction.Status.SCHEDULED,
    Auction.Status.LIVE,
    Auction.Status.ENDED,
}

PANEL_STATUSES = CATALOG_STATUSES | {Auction.Status.CANCELLED}


def _filter_auctions(request, auctions, *, statuses):
    status_value = request.query_params.get("status")
    if status_value is not None and status_value not in statuses:
        raise ValidationError({"detail": "Status inválido."})
    if status_value:
        auctions = auctions.filter(status=status_value)

    ordering = request.query_params.get("ordering", "ends_at")
    if ordering.lstrip("-") not in {
        "ends_at",
        "starts_at",
        "starting_bid_cents",
    }:
        raise ValidationError({"detail": "Ordenação inválida."})

    bounds = {}
    for name, lookup in (
        ("min_price", "starting_bid_cents__gte"),
        ("max_price", "starting_bid_cents__lte"),
    ):
        raw = request.query_params.get(name)
        if raw is None:
            continue
        try:
            value = int(raw)
        except ValueError:
            raise ValidationError({name: "Valor inválido."})
        if value < 0:
            raise ValidationError({name: "Valor inválido."})
        bounds[name] = value
        auctions = auctions.filter(**{lookup: value})

    if (
        "min_price" in bounds
        and "max_price" in bounds
        and bounds["min_price"] > bounds["max_price"]
    ):
        raise ValidationError({"detail": "Faixa de preço inválida."})

    query = request.query_params.get("q", "").strip()
    if query:
        auctions = auctions.filter(item__title__icontains=query)

    return auctions.order_by(ordering, "id")


def auction_payload(auction: Auction) -> dict:
    return {
        "id": auction.pk,
        "status": auction.status,
        "seller_pseudonym": pseudo(auction.seller),
        "item_id": auction.item_id,
        "item_title": auction.item.title,
        "item_image_url": auction.item.image_url or None,
        "starting_bid_cents": auction.starting_bid_cents,
        "minimum_increment_cents": auction.minimum_increment_cents,
        "starts_at": auction.starts_at.isoformat(),
        "ends_at": auction.ends_at.isoformat(),
        "winner_pseudonym": (
            pseudo(auction.winner) if auction.winner_id else None
        ),
    }


def _auction_or_404(auction_id) -> Auction:
    try:
        return Auction.objects.select_related(
            "item", "seller", "winner"
        ).get(pk=auction_id)
    except Auction.DoesNotExist:
        raise NotFound("Não encontrado.")


def _not_owner():
    return Response(
        {"detail": "Você não é o dono deste lote."},
        status=status.HTTP_403_FORBIDDEN,
    )


class AuctionListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAuctioneer]

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return super().get_permissions()

    def get(self, request):
        auctions = (
            Auction.objects.select_related("item", "seller", "winner")
            .annotate(bid_count=Count("bids"))
            .exclude(status=Auction.Status.CANCELLED)
        )
        auctions = _filter_auctions(
            request, auctions, statuses=CATALOG_STATUSES
        )

        paginator = AuctionPagination()
        page = paginator.paginate_queryset(auctions, request)

        return paginator.get_paginated_response(
            [
                {**auction_payload(auction), "bid_count": auction.bid_count}
                for auction in page
            ]
        )

    def post(self, request):
        serializer = AuctionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auction = serializer.save(seller=request.user)

        return Response(
            auction_payload(auction),
            status=status.HTTP_201_CREATED,
        )


class AuctionManageView(APIView):
    permission_classes = [IsAuthenticated, IsAuctioneer]

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return super().get_permissions()

    def get(self, request, auction_id):
        auction = _auction_or_404(auction_id)
        settle_if_expired(auction)

        return Response(
            {
                **auction_payload(auction),
                # Ficha da obra (descrição + atributos do catálogo) só no
                # detalhe — a lista continua enxuta.
                "item_description": auction.item.description or None,
                "item_attributes": auction.item.attributes or None,
            }
        )

    def patch(self, request, auction_id):
        auction = _auction_or_404(auction_id)

        if auction.seller_id != request.user.pk:
            return _not_owner()

        serializer = AuctionScheduleSerializer(
            instance=auction,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        try:
            auction = reschedule_auction(
                auction_id=auction.pk,
                starts_at=serializer.validated_data.get(
                    "starts_at", auction.starts_at
                ),
                ends_at=serializer.validated_data.get(
                    "ends_at", auction.ends_at
                ),
            )
        except RescheduleRejected:
            return Response(
                {"detail": "A programação só muda antes do lote começar."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(auction_payload(auction))


class AuctionCancelView(APIView):
    permission_classes = [IsAuthenticated, IsAuctioneer]

    def post(self, request, auction_id):
        auction = _auction_or_404(auction_id)

        if auction.seller_id != request.user.pk:
            return _not_owner()

        try:
            cancel_auction(auction_id=auction.pk, seller=request.user)
        except CancelRejected as exc:
            if str(exc) == "not_owner":
                return _not_owner()
            return Response(
                {"detail": "Este lote não pode mais ser cancelado."},
                status=status.HTTP_409_CONFLICT,
            )
        except HoldInconsistentError:
            return Response(
                {"detail": "Estado inconsistente de hold; contate o suporte."},
                status=status.HTTP_409_CONFLICT,
            )

        auction = Auction.objects.select_related("item").get(pk=auction.pk)

        return Response(auction_payload(auction))


class AuctionMineView(APIView):
    permission_classes = [IsAuthenticated, IsAuctioneer]

    def get(self, request):
        auctions = (
            Auction.objects.select_related("item", "seller", "winner")
            .annotate(bid_count=Count("bids"))
            .filter(seller=request.user)
        )
        auctions = _filter_auctions(
            request, auctions, statuses=PANEL_STATUSES
        )

        paginator = AuctionPagination()
        page = paginator.paginate_queryset(auctions, request)

        receipts = dict(
            Receipt.objects.filter(
                auction_id__in=[auction.pk for auction in page]
            ).values_list("auction_id", "amount_cents")
        )

        results = [
            {
                **auction_payload(auction),
                "bid_count": auction.bid_count,
                "received_cents": (
                    receipts.get(auction.pk, 0)
                    if auction.status == Auction.Status.ENDED
                    else None
                ),
            }
            for auction in page
        ]

        total = (
            Receipt.objects.filter(auction__seller=request.user)
            .aggregate(total=Sum("amount_cents"))["total"]
            or 0
        )

        return Response({
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": results,
            "summary": {"total_received_cents": total},
        })


class AuctionWonView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        auctions = (
            Auction.objects.select_related("item", "seller", "winner")
            .annotate(bid_count=Count("bids"))
            .filter(winner=request.user)
        )
        auctions = _filter_auctions(
            request, auctions, statuses=CATALOG_STATUSES
        )

        paginator = AuctionPagination()
        page = paginator.paginate_queryset(auctions, request)

        receipts = dict(
            Receipt.objects.filter(
                auction_id__in=[auction.pk for auction in page]
            ).values_list("auction_id", "public_uuid")
        )

        return paginator.get_paginated_response(
            [
                {
                    **auction_payload(auction),
                    "bid_count": auction.bid_count,
                    "receipt_public_uuid": (
                        str(receipts[auction.pk])
                        if auction.pk in receipts
                        else None
                    ),
                }
                for auction in page
            ]
        )

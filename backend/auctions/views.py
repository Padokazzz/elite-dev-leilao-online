from audit.services import pseudo
from django.db.models import Count
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuctioneer

from .models import Auction
from .serializers import AuctionCreateSerializer, AuctionScheduleSerializer
from .services import (
    CancelRejected,
    cancel_auction,
    settle_expired_auctions,
    settle_if_expired,
)


class AuctionPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 50


def auction_payload(auction: Auction) -> dict:
    return {
        "id": auction.pk,
        "status": auction.status,
        "seller_pseudonym": pseudo(auction.seller),
        "item_id": auction.item_id,
        "item_title": auction.item.title,
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
        settle_expired_auctions()

        status_value = request.query_params.get("status")
        if status_value is not None and status_value not in {
            Auction.Status.SCHEDULED,
            Auction.Status.LIVE,
            Auction.Status.ENDED,
        }:
            return Response(
                {"detail": "Status inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ordering = request.query_params.get("ordering", "ends_at")
        if ordering.lstrip("-") not in {
            "ends_at",
            "starts_at",
            "starting_bid_cents",
        }:
            return Response(
                {"detail": "Ordenação inválida."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        auctions = (
            Auction.objects.select_related("item", "seller", "winner")
            .annotate(bid_count=Count("bids"))
            .exclude(status=Auction.Status.CANCELLED)
            .order_by(ordering, "id")
        )

        if status_value:
            auctions = auctions.filter(status=status_value)

        query = request.query_params.get("q", "").strip()
        if query:
            auctions = auctions.filter(item__title__icontains=query)

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

        return Response(auction_payload(auction))

    def patch(self, request, auction_id):
        auction = _auction_or_404(auction_id)

        if auction.seller_id != request.user.pk:
            return _not_owner()

        auction = settle_if_expired(auction)

        if auction.status != Auction.Status.SCHEDULED:
            return Response(
                {"detail": "A programação só muda antes do lote começar."},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = AuctionScheduleSerializer(
            instance=auction,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        auction = serializer.save()

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

        auction = Auction.objects.select_related("item").get(pk=auction.pk)

        return Response(auction_payload(auction))

from django.db.models import Exists, OuterRef
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from auctions.models import Auction
from auctions.pagination import AuctionPagination
from auctions.services import settle_if_expired
from audit.services import pseudo
from receipts.models import Receipt

from .events import publish_bid_placed
from .exceptions import BidRejected
from .models import Bid
from .serializers import PlaceBidSerializer
from .services import place_bid


class AuctionBidsView(APIView):

    permission_classes = [IsAuthenticated]
    throttle_scope = "bid_place"

    def get_throttles(self):
        if self.request.method == "POST":
            return [ScopedRateThrottle()]
        return []

    def get(self, request, auction_id: int):
        auction = Auction.objects.filter(pk=auction_id).first()
        if auction is None:
            return Response(
                {"detail": "Não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        settle_if_expired(auction)

        bids = (
            Bid.objects.select_related("bidder")
            .filter(auction_id=auction_id)
            .order_by("-seq")[:50]
        )

        return Response(
            {
                "results": [
                    {
                        "seq": bid.seq,
                        "amount_cents": bid.amount_cents,
                        "accepted_at": bid.accepted_at,
                        # Pseudônimo estável (HMAC) — a identidade real
                        # nunca sai do back-end.
                        "bidder_pseudonym": pseudo(bid.bidder),
                        "is_you": bid.bidder_id == request.user.id,
                    }
                    for bid in bids
                ]
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, auction_id: int):
        serializer = PlaceBidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            outcome = place_bid(
                auction_id=auction_id,
                bidder=request.user,
                amount_cents=serializer.validated_data["amount_cents"],
            )
        except Auction.DoesNotExist:
            return Response(
                {"detail": "Lote não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except BidRejected as exc:
            return Response(exc.as_dict(), status=status.HTTP_400_BAD_REQUEST)

        publish_bid_placed(
            auction_id=auction_id,
            bidder_id=request.user.pk,
            bidder_pseudonym=pseudo(request.user),
            outcome=outcome,
        )

        return Response(
            {
                "bid": {
                    "seq": outcome.bid.seq,
                    "amount_cents": outcome.bid.amount_cents,
                    "accepted_at": outcome.bid.accepted_at,
                    "bidder_pseudonym": pseudo(request.user),
                },
                "extended": outcome.extended,
                "ends_at": outcome.ends_at,
                "next_minimum_cents": outcome.next_minimum_cents,
            },
            status=status.HTTP_201_CREATED,
        )


class MyBidsView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        later_exists = Exists(
            Bid.objects.filter(
                auction=OuterRef("auction_id"),
                seq__gt=OuterRef("seq"),
            )
        )

        bids = (
            Bid.objects.filter(bidder=request.user)
            .select_related("auction", "auction__item")
            .annotate(has_later=later_exists)
            .order_by("-accepted_at", "-pk")
        )

        paginator = AuctionPagination()
        page = paginator.paginate_queryset(bids, request)

        receipts = dict(
            Receipt.objects.filter(
                auction_id__in=[bid.auction_id for bid in page],
                winner=request.user,
            ).values_list("auction_id", "public_uuid")
        )

        results = []
        for bid in page:
            auction = bid.auction

            if bid.has_later:
                state = "outbid"
            elif auction.winner_id == request.user.pk:
                state = "won"
            elif auction.status == Auction.Status.CANCELLED:
                state = "cancelled"
            else:
                state = "leading"

            receipt = receipts.get(auction.pk)

            results.append({
                "seq": bid.seq,
                "amount_cents": bid.amount_cents,
                "accepted_at": bid.accepted_at.isoformat(),
                "auction_id": auction.pk,
                "auction_title": auction.item.title,
                "auction_status": auction.status,
                "ends_at": auction.ends_at.isoformat(),
                "state": state,
                "receipt_public_uuid": (
                    str(receipt) if state == "won" and receipt else None
                ),
            })

        return paginator.get_paginated_response(results)
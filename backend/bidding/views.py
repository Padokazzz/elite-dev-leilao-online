from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from auctions.models import Auction

from .exceptions import BidRejected
from .groups import auction_group
from .models import Bid
from .serializers import PlaceBidSerializer
from .services import BidOutcome, place_bid


def _publish_bid(auction_id: int, outcome: BidOutcome) -> None:
    async_to_sync(get_channel_layer().group_send)(
        auction_group(auction_id),
        {
            "type": "bid.placed",
            "bid": {
                "seq": outcome.bid.seq,
                "amount_cents": outcome.bid.amount_cents,
                "accepted_at": outcome.bid.accepted_at.isoformat(),
            },
            "extended": outcome.extended,
            "ends_at": outcome.ends_at.isoformat(),
            "next_minimum_cents": outcome.next_minimum_cents,
        },
    )


class AuctionBidsView(APIView):

    permission_classes = [IsAuthenticated]
    throttle_scope = "bid_place"

    def get_throttles(self):
        if self.request.method == "POST":
            return [ScopedRateThrottle()]
        return []

    def get(self, request, auction_id: int):
        bids = Bid.objects.filter(auction_id=auction_id).order_by("-seq")[:50]

        return Response(
            {
                "results": [
                    {
                        "seq": bid.seq,
                        "amount_cents": bid.amount_cents,
                        "accepted_at": bid.accepted_at,
                        
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

        _publish_bid(auction_id, outcome)

        return Response(
            {
                "bid": {
                    "seq": outcome.bid.seq,
                    "amount_cents": outcome.bid.amount_cents,
                    "accepted_at": outcome.bid.accepted_at,
                },
                "extended": outcome.extended,
                "ends_at": outcome.ends_at,
                "next_minimum_cents": outcome.next_minimum_cents,
            },
            status=status.HTTP_201_CREATED,
        )
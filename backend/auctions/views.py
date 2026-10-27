from audit.services import pseudo
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuctioneer

from .models import Auction
from .serializers import AuctionCreateSerializer, AuctionScheduleSerializer
from .services import CancelRejected, cancel_auction, settle_if_expired


def auction_payload(auction: Auction) -> dict:
    return {
        "id": auction.pk,
        "status": auction.status,
        "seller_id": auction.seller_id,
        "seller_pseudonym": pseudo(auction.seller),
        "item_id": auction.item_id,
        "item_title": auction.item.title,
        "starting_bid_cents": auction.starting_bid_cents,
        "minimum_increment_cents": auction.minimum_increment_cents,
        "starts_at": auction.starts_at.isoformat(),
        "ends_at": auction.ends_at.isoformat(),
        "winner_id": auction.winner_id,
        "winner_pseudonym": (
            pseudo(auction.winner) if auction.winner_id else None
        ),
    }


def _auction_or_404(auction_id) -> Auction:
    try:
        return Auction.objects.select_related("item").get(pk=auction_id)
    except Auction.DoesNotExist:
        raise NotFound("Não encontrado.")


def _not_owner():
    return Response(
        {"detail": "Você não é o dono deste lote."},
        status=status.HTTP_403_FORBIDDEN,
    )


class AuctionCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAuctioneer]

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

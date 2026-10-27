from django.db import transaction
from django.utils import timezone

from receipts.models import Receipt
from wallets.models import WalletTransaction
from wallets.services import lock_wallets, release_hold

from .models import Auction


def settle_auction(auction_id: int) -> bool:
    with transaction.atomic():
        auction = Auction.objects.select_for_update().get(pk=auction_id)

        if auction.status not in (Auction.Status.LIVE, Auction.Status.SCHEDULED):
            return False
        if timezone.now() < auction.ends_at:
            return False

        winner_bid = auction.bids.order_by("-seq").first()

        if winner_bid is None:
            auction.status = Auction.Status.ENDED
            auction.save(update_fields=["status", "updated_at"])
            return True

        wallets = lock_wallets([winner_bid.bidder_id, auction.seller_id])
        winner_wallet = wallets[winner_bid.bidder_id]
        seller_wallet = wallets[auction.seller_id]
        amount = winner_bid.amount_cents

        winner_wallet.balance_cents -= amount
        winner_wallet.committed_cents -= amount
        winner_wallet.save(
            update_fields=["balance_cents", "committed_cents", "updated_at"]
        )

        WalletTransaction.objects.create(
            wallet=winner_wallet,
            auction=auction,
            kind=WalletTransaction.Kind.SETTLEMENT,
            delta_cents=-amount,
            committed_delta_cents=-amount,
            description="Arremate liquidado",
        )

        seller_wallet.balance_cents += amount
        seller_wallet.save(update_fields=["balance_cents", "updated_at"])

        WalletTransaction.objects.create(
            wallet=seller_wallet,
            auction=auction,
            kind=WalletTransaction.Kind.SETTLEMENT,
            delta_cents=amount,
            committed_delta_cents=0,
            description="Arremate recebido",
        )

        auction.status = Auction.Status.ENDED
        auction.winner = winner_bid.bidder
        auction.save(update_fields=["status", "winner", "updated_at"])

        Receipt.objects.create(
            auction=auction,
            winner=winner_bid.bidder,
            seller=auction.seller,
            amount_cents=amount,
        )

        return True


def settle_expired_auctions() -> int:
    expired = list(
        Auction.objects.filter(
            status__in=[Auction.Status.LIVE, Auction.Status.SCHEDULED],
            ends_at__lte=timezone.now(),
        ).values_list("pk", flat=True)
    )

    return sum(1 for auction_id in expired if settle_auction(auction_id))


def settle_if_expired(auction: Auction) -> Auction:
    pending = auction.status in (
        Auction.Status.LIVE,
        Auction.Status.SCHEDULED,
    ) and auction.ends_at <= timezone.now()

    if pending and settle_auction(auction.pk):
        auction.refresh_from_db()

    return auction


class CancelRejected(Exception):
    pass


def cancel_auction(*, auction_id: int, seller) -> Auction:
    with transaction.atomic():
        auction = Auction.objects.select_for_update().get(pk=auction_id)

        if auction.seller_id != seller.pk:
            raise CancelRejected("not_owner")
        if auction.status not in (
            Auction.Status.SCHEDULED,
            Auction.Status.LIVE,
        ):
            raise CancelRejected("not_cancellable")

        latest = auction.bids.order_by("-seq").first()

        if latest is not None:
            wallets = lock_wallets([latest.bidder_id])
            release_hold(
                wallet=wallets[latest.bidder_id],
                auction=auction,
                bid=latest,
                description="Lance liberado pelo cancelamento do lote",
            )

        auction.status = Auction.Status.CANCELLED
        auction.save(update_fields=["status", "updated_at"])

    return auction

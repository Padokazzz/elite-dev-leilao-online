from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from auctions.models import Auction
from wallets.models import Wallet, WalletTransaction
from wallets.services import get_or_create_wallet

from .exceptions import BidRejected
from .models import Bid

User = get_user_model()

ANTI_SNIPE_WINDOW = timedelta(minutes=2)
ANTI_SNIPE_EXTENSION = timedelta(minutes=2)


@dataclass(frozen=True)
class BidOutcome:
    """Resultado rico para a view/WebSocket divulgar."""

    bid: Bid
    extended: bool
    ends_at: datetime
    next_minimum_cents: int


def _brl(cents: int) -> str:
    """Formata centavos em BRL sem passar por float."""
    return f"R$ {cents // 100},{cents % 100:02d}"


def _lock_wallets(user_ids) -> dict:
    """Trava carteiras em ordem determinística de user_id.

    Ordem fixa = sem ciclo possível entre transações concorrentes.
    """
    locked = {}
    for user_id in sorted(set(user_ids)):
        wallet, _ = Wallet.objects.select_for_update().get_or_create(
            user_id=user_id
        )
        locked[user_id] = wallet
    return locked


def _release_hold(*, wallet, auction, previous_bid) -> None:
    if wallet.committed_cents < previous_bid.amount_cents:
        raise BidRejected(
            "inconsistent_state",
            "Saldo comprometido inconsistente ao liberar o lance anterior.",
        )

    wallet.committed_cents -= previous_bid.amount_cents
    wallet.save(update_fields=["committed_cents", "updated_at"])

    WalletTransaction.objects.create(
        wallet=wallet,
        auction=auction,
        kind=WalletTransaction.Kind.BID_RELEASE,
        committed_delta_cents=-previous_bid.amount_cents,
        description=f"Lance #{previous_bid.seq} superado",
    )


def place_bid(*, auction_id: int, bidder: User, amount_cents: int) -> BidOutcome:
    if amount_cents <= 0:
        raise BidRejected("invalid_amount", "O lance deve ser maior que zero.")

    get_or_create_wallet(bidder)

    with transaction.atomic():
        auction = Auction.objects.select_for_update().get(pk=auction_id)

        now = timezone.now()

        if auction.status == Auction.Status.CANCELLED:
            raise BidRejected(
                "auction_cancelled", "Este lote foi cancelado."
            )
        if auction.status == Auction.Status.ENDED or now > auction.ends_at:
            raise BidRejected("auction_ended", "Este lote já foi encerrado.")
        if now < auction.starts_at:
            raise BidRejected(
                "auction_not_started", "Este lote ainda não começou."
            )

        if bidder.role == User.Role.AUCTIONEER:
            raise BidRejected(
                "auctioneer_cannot_bid",
                "Leiloeiros não podem dar lances.",
            )
        if auction.seller_id == bidder.id:
            raise BidRejected(
                "seller_cannot_bid",
                "Você não pode dar lance no seu próprio lote.",
            )

        previous = auction.bids.order_by("-seq").first()

        if previous is None:
            minimum = auction.starting_bid_cents
        else:
            if previous.bidder_id == bidder.id:
                raise BidRejected(
                    "already_leader",
                    "Você já está ganhando este lote.",
                )
            minimum = previous.amount_cents + auction.minimum_increment_cents

        if amount_cents < minimum:
            raise BidRejected(
                "below_minimum",
                f"O lance mínimo é {_brl(minimum)}.",
            )

        wallet_ids = [bidder.id]
        if previous is not None:
            wallet_ids.append(previous.bidder_id)
        wallets = _lock_wallets(wallet_ids)
        wallet = wallets[bidder.id]

        available = wallet.balance_cents - wallet.committed_cents
        if amount_cents > available:
            raise BidRejected(
                "insufficient_balance",
                f"Saldo disponível ({_brl(available)}) insuficiente "
                f"para este lance.",
            )

        if previous is not None:
            _release_hold(
                wallet=wallets[previous.bidder_id],
                auction=auction,
                previous_bid=previous,
            )

        seq = previous.seq + 1 if previous is not None else 1

        wallet.committed_cents += amount_cents
        wallet.save(update_fields=["committed_cents", "updated_at"])

        WalletTransaction.objects.create(
            wallet=wallet,
            auction=auction,
            kind=WalletTransaction.Kind.BID_HOLD,
            committed_delta_cents=amount_cents,
            description=f"Lance #{seq}",
        )

        bid = Bid.objects.create(
            auction=auction,
            bidder=bidder,
            amount_cents=amount_cents,
            seq=seq,
        )

        extended = False
        if auction.ends_at - now <= ANTI_SNIPE_WINDOW:
            auction.ends_at = now + ANTI_SNIPE_EXTENSION
            extended = True

        promoted = auction.status == Auction.Status.SCHEDULED
        if promoted:
            auction.status = Auction.Status.LIVE

        if extended or promoted:
            auction.save(update_fields=["ends_at", "status", "updated_at"])

        return BidOutcome(
            bid=bid,
            extended=extended,
            ends_at=auction.ends_at,
            next_minimum_cents=amount_cents + auction.minimum_increment_cents,
        )
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from auctions.models import Auction
from wallets.exceptions import HoldInconsistentError
from wallets.models import WalletTransaction
from wallets.services import (
    get_or_create_wallet,
    lock_wallets,
    release_hold,
)

from .exceptions import BidRejected
from .models import Bid

User = get_user_model()

ANTI_SNIPE_WINDOW = timedelta(minutes=2)
ANTI_SNIPE_EXTENSION = timedelta(minutes=2)

GENESIS_HASH = "0" * 64


def bid_hash(
    *, prev_hash, auction_id, seq, bidder_id, amount_cents, accepted_at
) -> str:
    payload = json.dumps(
        {
            "accepted_at": accepted_at.isoformat(),
            "amount_cents": amount_cents,
            "auction_id": auction_id,
            "bidder_id": bidder_id,
            "prev_hash": prev_hash,
            "seq": seq,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _release_hold(*, wallet, auction, previous_bid) -> None:
    try:
        release_hold(
            wallet=wallet,
            auction=auction,
            bid=previous_bid,
            description=f"Lance #{previous_bid.seq} superado",
        )
    except HoldInconsistentError as exc:
        raise BidRejected("inconsistent_state", str(exc)) from exc


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

        # Dono do lote antes do papel: é a regra mais específica e gera a
        # mensagem mais útil. Mesmo princípio de already_leader < minimum.
        if auction.seller_id == bidder.id:
            raise BidRejected(
                "seller_cannot_bid",
                "Você não pode dar lance no seu próprio lote.",
            )
        if bidder.role == User.Role.AUCTIONEER:
            raise BidRejected(
                "auctioneer_cannot_bid",
                "Leiloeiros não podem dar lances.",
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
        wallets = lock_wallets(wallet_ids)
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

        previous_hash = previous.hash if previous is not None else GENESIS_HASH
        bid.prev_hash = previous_hash
        bid.hash = bid_hash(
            prev_hash=previous_hash,
            auction_id=bid.auction_id,
            seq=bid.seq,
            bidder_id=bid.bidder_id,
            amount_cents=bid.amount_cents,
            accepted_at=bid.accepted_at,
        )
        bid.save(update_fields=["prev_hash", "hash"])

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
import hashlib
import hmac

from django.conf import settings
from django.contrib.auth import get_user_model

from bidding.services import GENESIS_HASH, bid_hash

User = get_user_model()

ROLE_LABELS = {
    User.Role.BIDDER: "Licitante",
    User.Role.AUCTIONEER: "Leiloeiro",
}


def pseudo(user) -> str:
    secret = settings.AUDIT_PSEUDO_SECRET.encode()
    digest = hmac.new(
        secret, str(user.pk).encode(), hashlib.sha256
    ).hexdigest()[:8]

    return f"{ROLE_LABELS[user.role]} #{digest}"


def verify_chain(auction) -> dict:
    chain = []
    tampered = None
    expected_prev = GENESIS_HASH
    expected_seq = 1

    for bid in auction.bids.order_by("seq").select_related("bidder"):
        if bid.seq != expected_seq:
            tampered = {
                "seq": bid.seq,
                "reason": "sequence_gap",
                "expected_seq": expected_seq,
            }
            break

        if bid.prev_hash != expected_prev:
            tampered = {
                "seq": bid.seq,
                "reason": "prev_hash_mismatch",
            }
            break

        computed = bid_hash(
            prev_hash=expected_prev,
            auction_id=bid.auction_id,
            seq=bid.seq,
            bidder_id=bid.bidder_id,
            amount_cents=bid.amount_cents,
            accepted_at=bid.accepted_at,
        )

        if computed != bid.hash:
            tampered = {
                "seq": bid.seq,
                "reason": "hash_mismatch",
            }
            break

        chain.append(
            {
                "seq": bid.seq,
                "amount_cents": bid.amount_cents,
                "accepted_at": bid.accepted_at,
                "bidder": pseudo(bid.bidder),
            }
        )

        expected_prev = bid.hash
        expected_seq += 1

    return {
        "auction_id": auction.pk,
        "intact": tampered is None,
        "chain": chain,
        "tampered": tampered,
    }

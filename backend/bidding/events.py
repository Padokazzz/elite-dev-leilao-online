from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .groups import auction_group


def _publish(auction_id: int, payload: dict) -> None:
    async_to_sync(get_channel_layer().group_send)(
        auction_group(auction_id), payload
    )


def publish_bid_placed(*, auction_id: int, bidder_id: int, outcome) -> None:
    _publish(
        auction_id,
        {
            "type": "bid.placed",
            "bidder_id": bidder_id,
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


def publish_auction_closed(
    *,
    auction_id: int,
    winner_id,
    winner_pseudonym,
    receipt_public_uuid,
    amount_cents,
) -> None:
    _publish(
        auction_id,
        {
            "type": "auction.closed",
            "auction_id": auction_id,
            "winner_id": winner_id,
            "winner_pseudonym": winner_pseudonym,
            "receipt_public_uuid": receipt_public_uuid,
            "amount_cents": amount_cents,
        },
    )


def publish_auction_cancelled(auction_id: int) -> None:
    _publish(
        auction_id,
        {"type": "auction.cancelled", "auction_id": auction_id},
    )

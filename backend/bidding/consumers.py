from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework.authtoken.models import Token

from auctions.models import Auction

from .groups import auction_group

CLOSE_UNAUTHENTICATED = 4401   
CLOSE_UNKNOWN_AUCTION = 4404


class AuctionConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.auction_id = self.scope["url_route"]["kwargs"]["auction_id"]
        self.group = auction_group(self.auction_id)

        user = await self._user_from_token()
        if user is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        if not await self._auction_exists():
            await self.close(code=CLOSE_UNKNOWN_AUCTION)
            return

        self.user = user
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json(await self._snapshot())

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        await self.send_json(
            {"type": "room.error", "detail": "Lance é enviado por POST."}
        )

    async def bid_placed(self, event):
        await self.send_json(
            {
                "type": "bid.placed",
                "bid": event["bid"],
                "extended": event["extended"],
                "ends_at": event["ends_at"],
                "next_minimum_cents": event["next_minimum_cents"],
            }
        )

    async def _user_from_token(self):
        query = parse_qs(self.scope.get("query_string", b"").decode())
        token = (query.get("token") or [None])[0]
        if not token:
            return None
        return await database_sync_to_async(self._lookup_token)(token)

    @staticmethod
    def _lookup_token(token: str):
        try:
            return Token.objects.select_related("user").get(key=token).user
        except Token.DoesNotExist:
            return None

    async def _auction_exists(self) -> bool:
        return await database_sync_to_async(
            Auction.objects.filter(pk=self.auction_id).exists
        )()

    async def _snapshot(self) -> dict:
        return await database_sync_to_async(self._auction_state)()

    def _auction_state(self) -> dict:
        auction = Auction.objects.get(pk=self.auction_id)
        last = auction.bids.order_by("-seq").first()

        return {
            "type": "room.snapshot",
            "auction_id": auction.pk,
            "status": auction.status,
            "ends_at": auction.ends_at.isoformat(),
            "starting_bid_cents": auction.starting_bid_cents,
            "minimum_increment_cents": auction.minimum_increment_cents,
            "last_bid_cents": last.amount_cents if last else None,
            "last_seq": last.seq if last else 0,
        }
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework.test import APITestCase

from auctions.models import Auction
from auctions.services import settle_auction
from bidding.services import place_bid
from bidding.tests import fund, make_auction, make_user

from .models import Receipt

User = get_user_model()


class ReceiptPublicAccessTests(APITestCase):

    def setUp(self):
        self.seller = make_user(
            username="rec_seller",
            email="rec_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="rec_alice", email="rec_alice@example.com"
        )
        self.bob = make_user(username="rec_bob", email="rec_bob@example.com")

        self.auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)

        fund(self.alice, 100_000)
        fund(self.bob, 100_000)

        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        place_bid(
            auction_id=self.auction.pk, bidder=self.bob, amount_cents=11_000
        )

        Auction.objects.filter(pk=self.auction.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )
        settle_auction(self.auction.pk)

        self.receipt = Receipt.objects.get(auction=self.auction)
        self.url = f"/api/receipts/{self.receipt.public_uuid}/"

    def test_receipt_is_reachable_without_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["public_uuid"], self.receipt.public_uuid)
        self.assertEqual(response.data["amount_cents"], 11_000)
        self.assertEqual(response.data["item_title"], "Obra de teste")
        self.assertRegex(response.data["winner"], r"^Licitante #[0-9a-f]{8}$")
        self.assertRegex(response.data["seller"], r"^Leiloeiro #[0-9a-f]{8}$")

    def test_receipt_payload_does_not_leak_identity(self):
        response = self.client.get(self.url)
        body = str(response.data)

        self.assertEqual(response.status_code, 200)

        for user in (self.alice, self.bob, self.seller):
            self.assertNotIn(user.email, body)
            self.assertNotIn(user.username, body)
        self.assertNotIn("@", body)

    def test_unknown_uuid_returns_404(self):
        response = self.client.get(f"/api/receipts/{uuid4()}/")

        self.assertEqual(response.status_code, 404)

    def test_malformed_uuid_returns_404(self):
        response = self.client.get("/api/receipts/nao-e-um-uuid/")

        self.assertEqual(response.status_code, 404)

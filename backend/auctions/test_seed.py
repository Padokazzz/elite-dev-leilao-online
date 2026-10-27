from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from rest_framework.test import APITestCase

from bidding.models import Bid
from catalog.models import AuctionItem
from catalog.services import ArtworkAPIError
from receipts.models import Receipt
from wallets.models import Wallet, WalletTransaction

from .models import Auction

User = get_user_model()

SEARCH_ARTWORKS = "auctions.management.commands.seed_demo.search_artworks"


def run_seed():
    output = StringIO()

    with patch(SEARCH_ARTWORKS, side_effect=ArtworkAPIError("offline")):
        call_command("seed_demo", stdout=output)

    return output.getvalue()


class SeedDemoTests(APITestCase):

    def test_seed_creates_the_demo_scenario(self):
        run_seed()

        self.assertEqual(User.objects.count(), 3)

        seller = User.objects.get(email="leiloeiro@demo.com")
        self.assertEqual(seller.role, User.Role.AUCTIONEER)
        self.assertTrue(seller.check_password("demo12345"))

        self.assertEqual(
            set(Auction.objects.values_list("status", flat=True)),
            {
                Auction.Status.LIVE,
                Auction.Status.SCHEDULED,
                Auction.Status.ENDED,
                Auction.Status.CANCELLED,
            },
        )

        receipt = Receipt.objects.get()
        self.assertEqual(receipt.winner.email, "licitante1@demo.com")
        self.assertEqual(receipt.amount_cents, 12_000)
        self.assertEqual(
            Wallet.objects.get(user=seller).balance_cents, 12_000
        )

    def test_seed_is_idempotent(self):
        run_seed()

        def snapshot():
            wallets = list(Wallet.objects.order_by("pk"))
            return (
                User.objects.count(),
                Auction.objects.count(),
                Bid.objects.count(),
                Receipt.objects.count(),
                WalletTransaction.objects.count(),
                [wallet.balance_cents for wallet in wallets],
                [wallet.committed_cents for wallet in wallets],
            )

        before = snapshot()
        run_seed()

        self.assertEqual(snapshot(), before)

    def test_live_lot_leaves_the_leader_committed_and_the_chain_intact(self):
        run_seed()

        live = Auction.objects.get(status=Auction.Status.LIVE)
        licitante2 = User.objects.get(email="licitante2@demo.com")

        wallet = Wallet.objects.get(user=licitante2)
        self.assertEqual(wallet.balance_cents, 500_000)
        self.assertEqual(wallet.committed_cents, 11_000)
        self.assertEqual(wallet.available_cents, 489_000)

        response = self.client.get(f"/api/auctions/{live.pk}/audit/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["intact"])

    def test_storefront_hides_the_cancelled_lot(self):
        run_seed()

        response = self.client.get("/api/auctions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)

        statuses = {row["status"] for row in response.data["results"]}
        self.assertNotIn(Auction.Status.CANCELLED, statuses)

    def test_seed_falls_back_to_embedded_items_without_network(self):
        output = run_seed()

        items = AuctionItem.objects.filter(source="demo")

        self.assertEqual(items.count(), 4)
        self.assertTrue(
            items.filter(title="Marina ao pôr do sol").exists()
        )
        self.assertIn("leiloeiro@demo.com", output)
        self.assertIn("demo12345", output)

    def test_rerun_rearms_an_expired_live_lot(self):
        run_seed()

        live = Auction.objects.get(status=Auction.Status.LIVE)
        Auction.objects.filter(pk=live.pk).update(
            ends_at=timezone.now() - timedelta(minutes=5)
        )

        run_seed()

        live.refresh_from_db()
        self.assertEqual(live.status, Auction.Status.LIVE)
        self.assertGreater(
            live.ends_at, timezone.now() + timedelta(minutes=5)
        )

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from bidding.services import place_bid
from bidding.tests import fund, make_auction, make_user
from catalog.models import AuctionItem
from receipts.models import Receipt
from wallets.models import Wallet, WalletTransaction

from .models import Auction
from .services import settle_auction, settle_expired_auctions

User = get_user_model()


class SettlementTests(APITestCase):

    def setUp(self):
        self.seller = make_user(
            username="sett_seller",
            email="sett_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="sett_alice", email="sett_alice@example.com"
        )
        self.bob = make_user(username="sett_bob", email="sett_bob@example.com")

        self.auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)

        fund(self.alice, 100_000)
        fund(self.bob, 100_000)

        self.token = Token.objects.create(user=self.alice)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def _expire(self, auction):
        Auction.objects.filter(pk=auction.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )
        auction.refresh_from_db()

    def test_expired_auction_pays_the_winner_and_the_seller(self):
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        place_bid(
            auction_id=self.auction.pk, bidder=self.bob, amount_cents=11_000
        )
        self._expire(self.auction)

        self.assertTrue(settle_auction(self.auction.pk))

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.ENDED)
        self.assertEqual(self.auction.winner, self.bob)

        winner = Wallet.objects.get(user=self.bob)
        self.assertEqual(winner.balance_cents, 100_000 - 11_000)
        self.assertEqual(winner.committed_cents, 0)
        self.assertEqual(winner.available_cents, 89_000)

        seller = Wallet.objects.get(user=self.seller)
        self.assertEqual(seller.balance_cents, 11_000)

        receipt = Receipt.objects.get(auction=self.auction)
        self.assertEqual(receipt.winner, self.bob)
        self.assertEqual(receipt.amount_cents, 11_000)

        total_committed = Wallet.objects.values_list("committed_cents", flat=True)
        self.assertEqual(sum(total_committed), 0)

    def test_auction_without_bids_ends_without_winner_or_receipt(self):
        self._expire(self.auction)

        self.assertTrue(settle_auction(self.auction.pk))

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.ENDED)
        self.assertIsNone(self.auction.winner)
        self.assertFalse(Receipt.objects.filter(auction=self.auction).exists())

    def test_settling_twice_does_not_move_money_twice(self):
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        self._expire(self.auction)

        self.assertTrue(settle_auction(self.auction.pk))
        self.assertFalse(settle_auction(self.auction.pk))

        seller = Wallet.objects.get(user=self.seller)
        self.assertEqual(seller.balance_cents, 10_000)
        self.assertEqual(Receipt.objects.filter(auction=self.auction).count(), 1)

    def test_a_live_auction_is_not_settled(self):
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )

        self.assertFalse(settle_auction(self.auction.pk))

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.LIVE)
        self.assertEqual(Wallet.objects.get(user=self.alice).committed_cents, 10_000)

    def test_command_settles_only_expired_auctions(self):
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        live = make_auction(self.seller)
        self._expire(self.auction)

        out = StringIO()
        call_command("settle_expired_auctions", stdout=out)

        self.auction.refresh_from_db()
        live.refresh_from_db()

        self.assertEqual(self.auction.status, Auction.Status.ENDED)
        self.assertEqual(live.status, Auction.Status.LIVE)
        self.assertIn("1 lote(s) liquidado(s)", out.getvalue())

    def test_reading_an_expired_auction_settles_it_on_the_spot(self):
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        self._expire(self.auction)

        response = self.client.get(f"/api/auctions/{self.auction.pk}/bids/")

        self.assertEqual(response.status_code, 200)

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.ENDED)
        self.assertTrue(Receipt.objects.filter(auction=self.auction).exists())


class AuctionManagementTests(APITestCase):

    def setUp(self):
        self.seller = make_user(
            username="mgr_seller",
            email="mgr_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.other = make_user(
            username="mgr_other",
            email="mgr_other@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="mgr_alice", email="mgr_alice@example.com"
        )
        self.bob = make_user(username="mgr_bob", email="mgr_bob@example.com")

        fund(self.alice, 100_000)
        fund(self.bob, 100_000)

        self.item = AuctionItem.objects.create(
            source="artic",
            external_id="mgr-item",
            title="Item de gestão",
        )

        self.url = "/api/auctions/"
        self._auth(self.seller)

    def _auth(self, user):
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def _payload(self, **overrides):
        now = timezone.now()
        data = {
            "item_id": self.item.pk,
            "starting_bid_cents": 10_000,
            "minimum_increment_cents": 500,
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=5)).isoformat(),
        }
        data.update(overrides)
        return data

    def _expire(self, auction):
        Auction.objects.filter(pk=auction.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )
        auction.refresh_from_db()

    def test_create_requires_authentication(self):
        self.client.credentials()

        response = self.client.post(self.url, self._payload(), format="json")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(Auction.objects.count(), 0)

    def test_bidder_cannot_create_an_auction(self):
        self._auth(self.alice)

        response = self.client.post(self.url, self._payload(), format="json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Auction.objects.count(), 0)

    def test_auctioneer_creates_a_scheduled_auction(self):
        response = self.client.post(self.url, self._payload(), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], Auction.Status.SCHEDULED)
        self.assertEqual(response.data["item_id"], self.item.pk)
        self.assertEqual(response.data["starting_bid_cents"], 10_000)
        self.assertEqual(response.data["seller_id"], self.seller.pk)
        self.assertEqual(Auction.objects.count(), 1)

    def test_create_rejects_an_unknown_item(self):
        response = self.client.post(
            self.url, self._payload(item_id=999_999), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Auction.objects.count(), 0)

    def test_create_rejects_ends_before_starts(self):
        now = timezone.now()
        response = self.client.post(
            self.url,
            self._payload(
                starts_at=(now + timedelta(hours=5)).isoformat(),
                ends_at=(now + timedelta(hours=1)).isoformat(),
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Auction.objects.count(), 0)

    def test_create_rejects_a_deadline_in_the_past(self):
        response = self.client.post(
            self.url,
            self._payload(
                ends_at=(timezone.now() - timedelta(hours=1)).isoformat()
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Auction.objects.count(), 0)

    def test_patch_is_rejected_for_another_auctioneer(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        self._auth(self.other)

        response = self.client.patch(
            f"{self.url}{auction.pk}/",
            {"ends_at": (timezone.now() + timedelta(hours=2)).isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.SCHEDULED)

    def test_patch_reschedules_a_scheduled_auction(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        new_end = timezone.now() + timedelta(hours=2)

        response = self.client.patch(
            f"{self.url}{auction.pk}/",
            {"ends_at": new_end.isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        auction.refresh_from_db()
        self.assertAlmostEqual(
            auction.ends_at, new_end, delta=timedelta(seconds=1)
        )

    def test_patch_after_bids_returns_conflict(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        original_end = auction.ends_at
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )

        response = self.client.patch(
            f"{self.url}{auction.pk}/",
            {"ends_at": (timezone.now() + timedelta(hours=2)).isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        auction.refresh_from_db()
        self.assertEqual(auction.ends_at, original_end)

    def test_patch_cannot_change_the_status(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)

        response = self.client.patch(
            f"{self.url}{auction.pk}/",
            {"status": Auction.Status.CANCELLED},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.SCHEDULED)

    def test_patch_cannot_change_the_price(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)

        response = self.client.patch(
            f"{self.url}{auction.pk}/",
            {"starting_bid_cents": 5_000},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["starting_bid_cents"], 10_000)
        auction.refresh_from_db()
        self.assertEqual(auction.starting_bid_cents, 10_000)

    def test_cancel_releases_the_leader_hold(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        place_bid(
            auction_id=auction.pk, bidder=self.bob, amount_cents=11_000
        )

        response = self.client.post(f"{self.url}{auction.pk}/cancel/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Auction.Status.CANCELLED)

        bob_wallet = Wallet.objects.get(user=self.bob)
        alice_wallet = Wallet.objects.get(user=self.alice)

        self.assertEqual(bob_wallet.committed_cents, 0)
        self.assertEqual(bob_wallet.balance_cents, 100_000)
        self.assertEqual(alice_wallet.committed_cents, 0)
        self.assertEqual(alice_wallet.balance_cents, 100_000)

        release = WalletTransaction.objects.get(
            wallet=bob_wallet,
            auction=auction,
            kind=WalletTransaction.Kind.BID_RELEASE,
        )
        self.assertEqual(release.committed_delta_cents, -11_000)
        self.assertEqual(
            WalletTransaction.objects.filter(
                auction=auction, kind=WalletTransaction.Kind.BID_RELEASE
            ).count(),
            2,
        )

    def test_cancel_without_bids_creates_no_refund(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)

        response = self.client.post(f"{self.url}{auction.pk}/cancel/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Auction.Status.CANCELLED)
        self.assertFalse(
            WalletTransaction.objects.filter(
                auction=auction, kind=WalletTransaction.Kind.BID_RELEASE
            ).exists()
        )

    def test_bidder_cannot_cancel_an_auction(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        self._auth(self.alice)

        response = self.client.post(f"{self.url}{auction.pk}/cancel/")

        self.assertEqual(response.status_code, 403)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.SCHEDULED)

    def test_cancel_is_rejected_for_another_auctioneer(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        self._auth(self.other)

        response = self.client.post(f"{self.url}{auction.pk}/cancel/")

        self.assertEqual(response.status_code, 403)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.SCHEDULED)

    def test_cancel_after_settlement_returns_conflict(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        self._expire(auction)
        settle_auction(auction.pk)

        response = self.client.post(f"{self.url}{auction.pk}/cancel/")

        self.assertEqual(response.status_code, 409)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.ENDED)
        self.assertEqual(
            Wallet.objects.get(user=self.alice).committed_cents, 0
        )

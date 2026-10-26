from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from bidding.services import place_bid
from bidding.tests import fund, make_auction, make_user
from receipts.models import Receipt
from wallets.models import Wallet

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

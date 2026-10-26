from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.core.cache import cache

from auctions.models import Auction
from catalog.models import AuctionItem
from wallets.models import Wallet, WalletTransaction
from wallets.services import deposit, get_or_create_wallet

from .exceptions import BidRejected
from .models import Bid
from .services import place_bid

from threading import Thread

from django.db import connections

from unittest.mock import patch

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from channels.testing import WebsocketCommunicator

from config.asgi import application

User = get_user_model()

def make_user(*, username, email, role=User.Role.BIDDER):
    return User.objects.create_user(
        username=username,
        email=email,
        password="Strong-Password!2026",
        role=role,
    )


def make_auction(
    seller,
    *,
    starting_bid_cents=10_000,
    minimum_increment_cents=1_000,
    starts_in=timedelta(hours=-1),
    ends_in=timedelta(hours=1),
    status=Auction.Status.LIVE,
):
    now = timezone.now()

    item = AuctionItem.objects.create(
        source="artic",
        external_id=f"item-{uuid4().hex[:12]}",
        title="Obra de teste",
    )

    return Auction.objects.create(
        item=item,
        seller=seller,
        starting_bid_cents=starting_bid_cents,
        minimum_increment_cents=minimum_increment_cents,
        starts_at=now + starts_in,
        ends_at=now + ends_in,
        status=status,
    )


def fund(user, cents):
    return deposit(
        wallet_id=get_or_create_wallet(user).pk,
        amount_cents=cents,
    )



class PlaceBidTestCase(TestCase):

    def setUp(self):
        self.seller = make_user(
            username="seller",
            email="seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(username="alice", email="alice@example.com")
        self.bob = make_user(username="bob", email="bob@example.com")

        self.auction = make_auction(self.seller)

        fund(self.alice, 100_000)
        fund(self.bob, 100_000)

    def assert_rejected(self, code, **kwargs):
        with self.assertRaises(BidRejected) as ctx:
            place_bid(**kwargs)

        self.assertEqual(
            ctx.exception.code,
            code,
            f"esperava {code}, veio {ctx.exception.code}",
        )
        return ctx.exception

class RejectionTests(PlaceBidTestCase):
    def test_invalid_amount(self):
        self.assert_rejected(
            "invalid_amount",
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=0,
        )

    def test_auction_not_started(self):
        auction = make_auction(
            self.seller,
            starts_in=timedelta(hours=1),
            ends_in=timedelta(hours=2),
        )
        self.assert_rejected(
            "auction_not_started",
            auction_id=auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

    def test_auction_ended_by_clock(self):
        auction = make_auction(
            self.seller,
            starts_in=timedelta(hours=-2),
            ends_in=timedelta(minutes=-1),
        )
        self.assert_rejected(
            "auction_ended",
            auction_id=auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

    def test_auction_ended_by_status(self):
        auction = make_auction(self.seller, status=Auction.Status.ENDED)
        self.assert_rejected(
            "auction_ended",
            auction_id=auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

    def test_auction_cancelled(self):
        auction = make_auction(self.seller, status=Auction.Status.CANCELLED)
        self.assert_rejected(
            "auction_cancelled",
            auction_id=auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

    def test_seller_cannot_bid_on_own_lot(self):
        self.assert_rejected(
            "seller_cannot_bid",
            auction_id=self.auction.pk,
            bidder=self.seller,
            amount_cents=10_000,
        )

    def test_auctioneer_cannot_bid_on_someone_elses_lot(self):
        rival = make_user(
            username="rival_seller",
            email="rival@example.com",
            role=User.Role.AUCTIONEER,
        )
        fund(rival, 100_000)
        self.assert_rejected(
            "auctioneer_cannot_bid",
            auction_id=self.auction.pk,
            bidder=rival,
            amount_cents=10_000,
        )

    def test_already_leader_cannot_cover_own_bid(self):
        place_bid(
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )
        self.assert_rejected(
            "already_leader",
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=11_000,
        )

    def test_below_minimum_on_first_bid(self):
        self.assert_rejected(
            "below_minimum",
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=9_999,
        )

    def test_below_minimum_on_raised_bid(self):
        place_bid(
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )
        # mínimo agora é 10_000 + 1_000 = 11_000
        self.assert_rejected(
            "below_minimum",
            auction_id=self.auction.pk,
            bidder=self.bob,
            amount_cents=10_999,
        )

    def test_insufficient_available_balance(self):
        poor = make_user(username="poor", email="poor@example.com")
        fund(poor, 5_000)          # R$ 50,00 — menos que o lance inicial
        self.assert_rejected(
            "insufficient_balance",
            auction_id=self.auction.pk,
            bidder=poor,
            amount_cents=10_000,
        )

class CommitmentTests(PlaceBidTestCase):
    def test_accepted_bid_commits_the_amount(self):
        place_bid(
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

        wallet = Wallet.objects.get(user=self.alice)
        self.assertEqual(wallet.balance_cents, 100_000)   # total não muda
        self.assertEqual(wallet.committed_cents, 10_000)  # travou
        self.assertEqual(wallet.available_cents, 90_000)  # livre caiu

    def test_ledger_records_hold_without_touching_total(self):
        place_bid(
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

        hold = WalletTransaction.objects.get(
            wallet__user=self.alice,
            kind=WalletTransaction.Kind.BID_HOLD,
        )
        self.assertEqual(hold.delta_cents, 0)              # total intacto
        self.assertEqual(hold.committed_delta_cents, 10_000)
        self.assertEqual(hold.auction_id, self.auction.pk)

    def test_being_outbid_releases_the_commitment(self):
        place_bid(
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )
        place_bid(
            auction_id=self.auction.pk,
            bidder=self.bob,
            amount_cents=11_000,
        )

        alice = Wallet.objects.get(user=self.alice)
        bob = Wallet.objects.get(user=self.bob)

        self.assertEqual(alice.balance_cents, 100_000)
        self.assertEqual(alice.committed_cents, 0)
        self.assertEqual(alice.available_cents, 100_000)

        self.assertEqual(bob.committed_cents, 11_000)
        self.assertEqual(bob.available_cents, 89_000)

    def test_release_is_recorded_in_the_ledger(self):
        place_bid(
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )
        place_bid(
            auction_id=self.auction.pk,
            bidder=self.bob,
            amount_cents=11_000,
        )

        release = WalletTransaction.objects.get(
            wallet__user=self.alice,
            kind=WalletTransaction.Kind.BID_RELEASE,
        )
        self.assertEqual(release.committed_delta_cents, -10_000)
        self.assertEqual(release.delta_cents, 0)
        self.assertIn("#1", release.description)

    def test_ledger_invariant_holds_after_a_dispute(self):
        for amount in (10_000, 11_000, 12_500):
            bidder = self.alice if amount != 11_000 else self.bob
            place_bid(
                auction_id=self.auction.pk,
                bidder=bidder,
                amount_cents=amount,
            )

        for user in (self.alice, self.bob):
            wallet = Wallet.objects.get(user=user)
            rows = WalletTransaction.objects.filter(wallet=wallet)

            total_delta = rows.aggregate(s=Sum("delta_cents"))["s"] or 0
            committed_delta = (
                rows.aggregate(s=Sum("committed_delta_cents"))["s"] or 0
            )

            self.assertEqual(total_delta, wallet.balance_cents)
            self.assertEqual(committed_delta, wallet.committed_cents)
            self.assertGreaterEqual(wallet.available_cents, 0)

    def test_seq_starts_at_one_and_increments(self):
        first = place_bid(
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )
        second = place_bid(
            auction_id=self.auction.pk,
            bidder=self.bob,
            amount_cents=11_000,
        )

        self.assertEqual(first.bid.seq, 1)
        self.assertEqual(second.bid.seq, 2)
        self.assertEqual(Bid.objects.filter(auction=self.auction).count(), 2)

class AntiSnipeTests(PlaceBidTestCase):
    def test_bid_close_to_the_deadline_extends_it(self):
        auction = make_auction(self.seller, ends_in=timedelta(seconds=30))
        original_end = auction.ends_at

        outcome = place_bid(
            auction_id=auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

        self.assertTrue(outcome.extended)
        self.assertGreater(outcome.ends_at, original_end)

        self.assertEqual(
            Auction.objects.get(pk=auction.pk).ends_at,
            outcome.ends_at,
        )

    def test_extension_gives_a_full_two_minute_window(self):
        auction = make_auction(self.seller, ends_in=timedelta(seconds=1))

        outcome = place_bid(
            auction_id=auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

        self.assertTrue(outcome.extended)
        self.assertGreaterEqual(
            outcome.ends_at,
            timezone.now() + timedelta(minutes=2, seconds=-5),
        )

    def test_bid_exactly_two_minutes_before_deadline_still_extends(self):
        auction = make_auction(self.seller, ends_in=timedelta(minutes=2))

        outcome = place_bid(
            auction_id=auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

        self.assertTrue(outcome.extended)

    def test_bid_far_from_deadline_does_not_extend(self):
        auction = make_auction(self.seller, ends_in=timedelta(minutes=10))
        original_end = auction.ends_at

        outcome = place_bid(
            auction_id=auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )

        self.assertFalse(outcome.extended)
        self.assertEqual(outcome.ends_at, original_end)
        self.assertEqual(
            Auction.objects.get(pk=auction.pk).ends_at,
            original_end,
        )

    def test_outcome_reports_the_next_minimum(self):
        first = place_bid(
            auction_id=self.auction.pk,
            bidder=self.alice,
            amount_cents=10_000,
        )
        second = place_bid(
            auction_id=self.auction.pk,
            bidder=self.bob,
            amount_cents=11_000,
        )

        self.assertEqual(first.next_minimum_cents, 11_000)
        self.assertEqual(second.next_minimum_cents, 12_000)

class ConcurrentBidTests(TransactionTestCase):
    THREADS = 10

    def setUp(self):
        self.seller = make_user(
            username="seller_race",
            email="seller-race@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.auction = make_auction(self.seller)
        self.original_end = self.auction.ends_at

        self.bidders = [
            make_user(username=f"racer{i}", email=f"racer{i}@example.com")
            for i in range(self.THREADS)
        ]
        for bidder in self.bidders:
            fund(bidder, 1_000_000)     # R$ 10.000,00 cada

    def test_concurrent_bids_are_serialized_by_the_auction_lock(self):
        auction_id = self.auction.pk
        amount = self.auction.starting_bid_cents
        results = []  # list.append é atômico sob o GIL do CPython

        def attempt(user_id):
            try:
                bidder = User.objects.get(pk=user_id)
                outcome = place_bid(
                    auction_id=auction_id,
                    bidder=bidder,
                    amount_cents=amount,
                )
                results.append(("accepted", outcome.bid.seq))
            except BidRejected as exc:
                results.append((exc.code, None))
            except Exception as exc:            # noqa: BLE001
                results.append((type(exc).__name__, str(exc)))
            finally:
                connections.close_all()        # conexão é por thread

        threads = [
            Thread(target=attempt, args=(bidder.pk,), daemon=True)
            for bidder in self.bidders
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(len(results), self.THREADS, results)

        accepted = [r for r in results if r[0] == "accepted"]
        rejected = [r for r in results if r[0] != "accepted"]
        self.assertEqual(len(accepted), 1, results)
        self.assertEqual(len(rejected), self.THREADS - 1, results)

        self.assertEqual({code for code, _ in rejected}, {"below_minimum"}, results)

        self.assertNotIn("IntegrityError", {code for code, _ in results}, results)

        bids = Bid.objects.filter(auction_id=auction_id)
        self.assertEqual(bids.count(), 1)
        winner = bids.get()
        self.assertEqual(winner.seq, 1)

        for bidder in self.bidders:
            wallet = Wallet.objects.get(user=bidder)
            if bidder.pk == winner.bidder_id:
                self.assertEqual(wallet.committed_cents, amount)
            else:
                self.assertEqual(wallet.committed_cents, 0)
            self.assertGreaterEqual(wallet.available_cents, 0)

        self.assertEqual(
            Auction.objects.get(pk=auction_id).ends_at,
            self.original_end,
        )

class BidEndpointTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.seller = make_user(
            username="seller_api",
            email="seller_api@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(username="alice_api", email="alice_api@example.com")
        self.bob = make_user(username="bob_api", email="bob_api@example.com")

        self.auction = make_auction(self.seller)
        self.url = f"/api/auctions/{self.auction.pk}/bids/"

        fund(self.alice, 100_000)
        fund(self.bob, 100_000)

        self.alice_token = Token.objects.create(user=self.alice)
        self.bob_token = Token.objects.create(user=self.bob)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.alice_token.key}"
        )

    def test_post_accepts_a_bid_and_returns_201(self):
        response = self.client.post(
            self.url, {"amount_cents": 10_000}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["bid"]["seq"], 1)
        self.assertEqual(response.data["bid"]["amount_cents"], 10_000)
        self.assertFalse(response.data["extended"])
        self.assertEqual(response.data["next_minimum_cents"], 11_000)

    def test_post_requires_authentication(self):
        self.client.credentials()  # limpa o cabeçalho

        response = self.client.post(
            self.url, {"amount_cents": 10_000}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_below_minimum_returns_400_with_a_stable_code(self):
        response = self.client.post(
            self.url, {"amount_cents": 5_000}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "below_minimum")

    def test_post_to_unknown_auction_returns_404(self):
        response = self.client.post(
            "/api/auctions/999999/bids/",
            {"amount_cents": 10_000},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_malformed_payload_returns_a_field_error(self):
        response = self.client.post(
            self.url, {"amount_cents": "dez reais"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("amount_cents", response.data)

    def test_get_returns_the_history_newest_first(self):
        self.client.post(self.url, {"amount_cents": 10_000}, format="json")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.bob_token.key}"
        )
        self.client.post(self.url, {"amount_cents": 12_000}, format="json")

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.alice_token.key}"
        )
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["seq"] for row in response.data["results"]], [2, 1])
        self.assertFalse(response.data["results"][0]["is_you"])   # lance do bob
        self.assertTrue(response.data["results"][1]["is_you"])    # lance da alice

    @patch(
        "rest_framework.throttling.ScopedRateThrottle.get_rate",
        return_value="2/min",
    )
    def test_posts_are_rate_limited_and_the_history_is_not(self, _mock):
        # payload sempre recusado (abaixo do mínimo): barato, sem escrita
        payload = {"amount_cents": 1}
        for _ in range(2):
            response = self.client.post(self.url, payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # a sala continua legível: o GET não entra no limite
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

class AuctionRoomTests(TransactionTestCase):
    def setUp(self):
        self.seller = make_user(
            username="room_seller",
            email="room_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="room_alice", email="room_alice@example.com"
        )
        self.auction = make_auction(self.seller)
        self.token = Token.objects.create(user=self.alice)
        self.origin = [(b"origin", b"http://testserver")]

    def _room(self, token=None):
        path = f"/ws/auctions/{self.auction.pk}/"
        if token:
            path = f"{path}?token={token}"
        return WebsocketCommunicator(application, path, headers=self.origin)

    async def test_connects_with_token_and_receives_snapshot(self):
        communicator = self._room(self.token.key)

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        snapshot = await communicator.receive_json_from(timeout=2)

        self.assertEqual(snapshot["type"], "room.snapshot")
        self.assertEqual(snapshot["auction_id"], self.auction.pk)
        self.assertEqual(snapshot["status"], "live")
        self.assertIsNone(snapshot["last_bid_cents"])

        await communicator.disconnect()

    async def test_rejects_connection_without_token(self):
        connected, code = await self._room().connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_rejects_foreign_origin(self):
        communicator = WebsocketCommunicator(
            application,
            f"/ws/auctions/{self.auction.pk}/?token={self.token.key}",
            headers=[(b"origin", b"http://evil.example")],
        )

        connected, _ = await communicator.connect()

        self.assertFalse(connected)

    async def test_rejects_unknown_auction(self):
        communicator = WebsocketCommunicator(
            application,
            "/ws/auctions/999999/?token=" + self.token.key,
            headers=self.origin,
        )

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4404)

    async def test_lance_nao_e_aceito_pelo_socket(self):
        communicator = self._room(self.token.key)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from(timeout=2)  # descarta o snapshot

        await communicator.send_json_to(
            {"type": "bid", "amount_cents": 10_000}
        )
        reply = await communicator.receive_json_from(timeout=2)

        self.assertEqual(reply["type"], "room.error")

        await communicator.disconnect()
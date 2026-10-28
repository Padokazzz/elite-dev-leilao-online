from datetime import timedelta
from io import StringIO
from threading import Barrier, Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import OperationalError, connections
from django.db.models import Sum
from django.test import TransactionTestCase
from django.utils import timezone

import signal

from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from audit.services import pseudo
from bidding.services import place_bid
from bidding.tests import fund, make_auction, make_user
from catalog.models import AuctionItem
from receipts.models import Receipt
from wallets.exceptions import HoldInconsistentError
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

    def test_settle_refuses_when_the_hold_is_inconsistent(self):
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        Wallet.objects.filter(user=self.alice).update(committed_cents=0)
        self._expire(self.auction)

        with self.assertRaises(HoldInconsistentError):
            settle_auction(self.auction.pk)

        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.LIVE)
        self.assertEqual(
            Wallet.objects.get(user=self.alice).balance_cents, 100_000
        )
        seller_wallet, _ = Wallet.objects.get_or_create(user=self.seller)
        self.assertEqual(seller_wallet.balance_cents, 0)
        self.assertFalse(Receipt.objects.filter(auction=self.auction).exists())

    def test_a_poisoned_lot_does_not_block_the_others(self):
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        healthy = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        place_bid(
            auction_id=healthy.pk, bidder=self.bob, amount_cents=10_000
        )

        Wallet.objects.filter(user=self.alice).update(committed_cents=0)
        self._expire(self.auction)
        self._expire(healthy)

        with patch("auctions.services.logger") as logger:
            count = settle_expired_auctions()

        logger.exception.assert_called()
        self.assertEqual(count, 1)
        self.auction.refresh_from_db()
        healthy.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.LIVE)
        self.assertFalse(Receipt.objects.filter(auction=self.auction).exists())
        self.assertEqual(healthy.status, Auction.Status.ENDED)
        self.assertTrue(Receipt.objects.filter(auction=healthy).exists())

    def test_worker_keeps_running_after_a_failed_round(self):
        previous_term = signal.getsignal(signal.SIGTERM)
        previous_int = signal.getsignal(signal.SIGINT)
        stderr = StringIO()
        stdout = StringIO()

        try:
            with patch(
                "auctions.management.commands.settle_auctions_loop"
                ".settle_expired_auctions",
                side_effect=[
                    OperationalError("banco indisponível"),
                    KeyboardInterrupt(),
                ],
            ) as tick:
                with self.assertRaises(KeyboardInterrupt):
                    call_command(
                        "settle_auctions_loop",
                        interval=0,
                        stderr=stderr,
                        stdout=stdout,
                    )
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            signal.signal(signal.SIGINT, previous_int)

        self.assertEqual(tick.call_count, 2)
        self.assertIn("falha na rodada", stderr.getvalue())
        self.assertIn("worker de liquidação ativo", stdout.getvalue())


class ConcurrentSettlementTests(TransactionTestCase):

    def setUp(self):
        self.seller = make_user(
            username="cset_seller",
            email="cset_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="cset_alice", email="cset_alice@example.com"
        )
        self.auction = make_auction(
            self.seller, status=Auction.Status.SCHEDULED
        )
        fund(self.alice, 100_000)
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        Auction.objects.filter(pk=self.auction.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )

    def test_concurrent_settlements_move_the_money_exactly_once(self):
        auction_id = self.auction.pk
        barrier = Barrier(2)
        results = []

        def settle():
            try:
                barrier.wait(timeout=10)
                results.append(settle_auction(auction_id))
            except Exception as exc:
                results.append(type(exc).__name__)
            finally:
                connections.close_all()

        threads = [Thread(target=settle, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(len(results), 2, results)
        self.assertEqual(sorted(results, key=str), [False, True], results)

        auction = Auction.objects.get(pk=auction_id)
        self.assertEqual(auction.status, Auction.Status.ENDED)
        self.assertEqual(auction.winner_id, self.alice.pk)
        self.assertEqual(Receipt.objects.filter(auction_id=auction_id).count(), 1)

        seller_wallet = Wallet.objects.get(user=self.seller)
        self.assertEqual(seller_wallet.balance_cents, 10_000)

        winner_wallet = Wallet.objects.get(user=self.alice)
        self.assertEqual(winner_wallet.balance_cents, 90_000)
        self.assertEqual(winner_wallet.committed_cents, 0)

        self.assertEqual(
            Wallet.objects.aggregate(total=Sum("balance_cents"))["total"],
            100_000,
        )


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
        self.assertEqual(response.data["seller_pseudonym"], pseudo(self.seller))
        self.assertNotIn("seller_id", response.data)
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

    def test_create_rejects_a_past_window_that_already_started(self):
        now = timezone.now()
        response = self.client.post(
            self.url,
            self._payload(
                starts_at=(now - timedelta(hours=3)).isoformat(),
                ends_at=(now - timedelta(hours=1)).isoformat(),
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

    def test_patch_rejects_an_end_in_the_past(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        original_end = auction.ends_at

        response = self.client.patch(
            f"{self.url}{auction.pk}/",
            {"ends_at": (timezone.now() - timedelta(minutes=5)).isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        auction.refresh_from_db()
        self.assertEqual(auction.ends_at, original_end)

    def test_patch_settles_an_expired_lot_before_rejecting(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        self._expire(auction)

        response = self.client.patch(
            f"{self.url}{auction.pk}/",
            {"ends_at": (timezone.now() + timedelta(hours=2)).isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.ENDED)
        self.assertTrue(Receipt.objects.filter(auction=auction).exists())

    def test_patch_only_moves_the_boundary_it_received(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        original_start = auction.starts_at
        new_end = timezone.now() + timedelta(hours=3)

        response = self.client.patch(
            f"{self.url}{auction.pk}/",
            {"ends_at": new_end.isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        auction.refresh_from_db()
        self.assertEqual(auction.starts_at, original_start)
        self.assertAlmostEqual(
            auction.ends_at, new_end, delta=timedelta(seconds=1)
        )

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

    def test_cancel_with_inconsistent_hold_returns_conflict(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        Wallet.objects.filter(user=self.alice).update(committed_cents=0)

        response = self.client.post(f"{self.url}{auction.pk}/cancel/")

        self.assertEqual(response.status_code, 409)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.LIVE)
        self.assertEqual(
            Wallet.objects.get(user=self.alice).committed_cents, 0
        )


class AuctionVitrineTests(APITestCase):

    def setUp(self):
        self.seller = make_user(
            username="vit_seller",
            email="vit_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="vit_alice", email="vit_alice@example.com"
        )
        fund(self.alice, 100_000)

        self.url = "/api/auctions/"

    def _auction(self, *, title="Obra de teste", **kwargs):
        auction = make_auction(self.seller, **kwargs)

        if title != "Obra de teste":
            auction.item.title = title
            auction.item.save(update_fields=["title"])

        return auction

    def _expire(self, auction):
        Auction.objects.filter(pk=auction.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )
        auction.refresh_from_db()

    def test_list_is_public(self):
        auction = self._auction()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], auction.pk)
        self.assertEqual(
            response.data["results"][0]["seller_pseudonym"],
            pseudo(self.seller),
        )

    def test_list_hides_cancelled_lots(self):
        live = self._auction(status=Auction.Status.LIVE)
        self._auction(status=Auction.Status.CANCELLED)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], live.pk)

    def test_list_filters_by_status(self):
        self._auction(status=Auction.Status.LIVE)
        scheduled = self._auction(
            status=Auction.Status.SCHEDULED,
            starts_in=timedelta(hours=1),
            ends_in=timedelta(hours=5),
        )

        response = self.client.get(self.url, {"status": "scheduled"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], scheduled.pk)

    def test_list_rejects_unknown_status_and_ordering(self):
        self.assertEqual(
            self.client.get(self.url, {"status": "cancelled"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(self.url, {"ordering": "seller_id"}).status_code,
            400,
        )

    def test_list_searches_by_title(self):
        picasso = self._auction(title="Guernica")
        self._auction(title="Noite estrelada")

        response = self.client.get(self.url, {"q": "guern"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], picasso.pk)

    def test_list_orders_soonest_ending_first(self):
        late = self._auction(ends_in=timedelta(hours=5))
        soon = self._auction(ends_in=timedelta(hours=1))

        response = self.client.get(self.url)

        ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(ids, [soon.pk, late.pk])

    def test_list_paginates(self):
        for hours in range(1, 16):
            self._auction(ends_in=timedelta(hours=hours))

        first = self.client.get(self.url, {"page_size": 10})
        second = self.client.get(self.url, {"page_size": 10, "page": 2})

        self.assertEqual(first.data["count"], 15)
        self.assertEqual(len(first.data["results"]), 10)
        self.assertIsNotNone(first.data["next"])
        self.assertEqual(len(second.data["results"]), 5)
        self.assertIsNone(second.data["next"])

        ids = [item["id"] for item in first.data["results"]]
        ids += [item["id"] for item in second.data["results"]]
        self.assertEqual(len(set(ids)), 15)

    def test_list_caps_page_size(self):
        for hours in range(1, 61):
            self._auction(ends_in=timedelta(hours=hours))

        response = self.client.get(self.url, {"page_size": 999})

        self.assertEqual(response.data["count"], 60)
        self.assertEqual(len(response.data["results"]), 50)

    def test_list_leaves_settlement_to_the_worker(self):
        auction = self._auction(status=Auction.Status.SCHEDULED)
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        self._expire(auction)

        response = self.client.get(self.url)

        item = response.data["results"][0]
        self.assertEqual(item["status"], Auction.Status.LIVE)
        self.assertIsNone(item["winner_pseudonym"])
        self.assertEqual(item["bid_count"], 1)
        self.assertFalse(Receipt.objects.filter(auction=auction).exists())
        self.assertEqual(
            Wallet.objects.get(user=self.alice).committed_cents, 10_000
        )

        settle_auction(auction.pk)

        response = self.client.get(self.url)

        item = response.data["results"][0]
        self.assertEqual(item["status"], Auction.Status.ENDED)
        self.assertEqual(item["winner_pseudonym"], pseudo(self.alice))

    def test_detail_is_public_and_hides_identity(self):
        auction = self._auction()

        response = self.client.get(f"{self.url}{auction.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], auction.pk)
        self.assertEqual(
            response.data["seller_pseudonym"], pseudo(self.seller)
        )
        self.assertNotIn("seller_id", response.data)
        self.assertNotIn("winner_id", response.data)

    def test_detail_returns_404_for_unknown_id(self):
        response = self.client.get(f"{self.url}999999/")

        self.assertEqual(response.status_code, 404)

    def test_payload_carries_item_image(self):
        auction = self._auction()
        auction.item.image_url = "https://example.com/artwork.jpg"
        auction.item.save(update_fields=["image_url"])
        blank = self._auction(title="Outra obra")

        listing = self.client.get(self.url)
        detail = self.client.get(f"{self.url}{auction.pk}/")
        rows = {row["id"]: row for row in listing.data["results"]}

        self.assertEqual(
            rows[auction.pk]["item_image_url"],
            "https://example.com/artwork.jpg",
        )
        self.assertIsNone(rows[blank.pk]["item_image_url"])
        self.assertEqual(
            detail.data["item_image_url"],
            "https://example.com/artwork.jpg",
        )

    def test_detail_includes_artwork_information(self):
        auction = self._auction()
        auction.item.description = "Óleo sobre tela, escola flamenga."
        auction.item.attributes = {
            "artist": "Escola flamenga",
            "date": "séc. XVII",
            "medium": "Óleo sobre tela",
            "dimensions": "62 × 48 cm",
            "source_url": "https://www.artic.edu/artworks/123",
        }
        auction.item.save(update_fields=["description", "attributes"])
        plain = self._auction(title="Obra sem ficha")

        detail = self.client.get(f"{self.url}{auction.pk}/")
        plain_detail = self.client.get(f"{self.url}{plain.pk}/")
        listing = self.client.get(self.url)
        row = next(
            item
            for item in listing.data["results"]
            if item["id"] == auction.pk
        )

        self.assertEqual(
            detail.data["item_description"],
            "Óleo sobre tela, escola flamenga.",
        )
        self.assertEqual(
            detail.data["item_attributes"]["artist"],
            "Escola flamenga",
        )
        self.assertEqual(
            detail.data["item_attributes"]["source_url"],
            "https://www.artic.edu/artworks/123",
        )
        self.assertIsNone(plain_detail.data["item_description"])
        self.assertIsNone(plain_detail.data["item_attributes"])
        # A lista continua enxuta: a ficha só vem no detalhe.
        self.assertNotIn("item_description", row)
        self.assertNotIn("item_attributes", row)

    def test_detail_settles_an_expired_auction(self):
        auction = self._auction(status=Auction.Status.SCHEDULED)
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        self._expire(auction)

        response = self.client.get(f"{self.url}{auction.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Auction.Status.ENDED)
        self.assertEqual(
            response.data["winner_pseudonym"], pseudo(self.alice)
        )
        self.assertTrue(Receipt.objects.filter(auction=auction).exists())


class AuctionPanelTests(APITestCase):

    def setUp(self):
        self.seller = make_user(
            username="pan_seller",
            email="pan_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.other = make_user(
            username="pan_other",
            email="pan_other@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="pan_alice", email="pan_alice@example.com"
        )
        self.bob = make_user(username="pan_bob", email="pan_bob@example.com")

        fund(self.alice, 100_000)
        fund(self.bob, 100_000)

        self.url = "/api/auctions/"

    def _auth(self, user):
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def _expire(self, auction):
        Auction.objects.filter(pk=auction.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )
        auction.refresh_from_db()

    def test_list_filters_by_price_range(self):
        cheap = make_auction(self.seller, starting_bid_cents=10_000)
        expensive = make_auction(self.seller, starting_bid_cents=50_000)

        above = self.client.get(self.url, {"min_price": "20000"})
        below = self.client.get(self.url, {"max_price": "20000"})

        self.assertEqual(above.data["count"], 1)
        self.assertEqual(above.data["results"][0]["id"], expensive.pk)
        self.assertEqual(below.data["count"], 1)
        self.assertEqual(below.data["results"][0]["id"], cheap.pk)

    def test_list_rejects_an_invalid_price_range(self):
        crossed = self.client.get(
            self.url, {"min_price": "60000", "max_price": "10000"}
        )
        garbled = self.client.get(self.url, {"min_price": "abc"})

        self.assertEqual(crossed.status_code, 400)
        self.assertEqual(garbled.status_code, 400)

    def test_mine_requires_authentication(self):
        self.client.credentials()

        response = self.client.get(f"{self.url}mine/")

        self.assertEqual(response.status_code, 401)

    def test_bidder_cannot_open_the_panel(self):
        self._auth(self.alice)

        response = self.client.get(f"{self.url}mine/")

        self.assertEqual(response.status_code, 403)

    def test_mine_returns_only_my_lots_including_cancelled(self):
        live = make_auction(self.seller, status=Auction.Status.LIVE)
        cancelled = make_auction(
            self.seller, status=Auction.Status.CANCELLED
        )
        make_auction(self.other, status=Auction.Status.LIVE)

        self._auth(self.seller)
        panel = self.client.get(f"{self.url}mine/")
        catalog = self.client.get(self.url)

        self.assertEqual(panel.status_code, 200)
        self.assertEqual(panel.data["count"], 2)
        self.assertEqual(
            {row["id"] for row in panel.data["results"]},
            {live.pk, cancelled.pk},
        )
        self.assertEqual(catalog.data["count"], 2)
        self.assertNotIn(
            cancelled.pk,
            {row["id"] for row in catalog.data["results"]},
        )

    def test_mine_allows_the_cancelled_status_filter(self):
        make_auction(self.seller, status=Auction.Status.CANCELLED)
        make_auction(self.seller, status=Auction.Status.LIVE)

        self._auth(self.seller)
        panel = self.client.get(
            f"{self.url}mine/", {"status": "cancelled"}
        )
        catalog = self.client.get(self.url, {"status": "cancelled"})

        self.assertEqual(panel.status_code, 200)
        self.assertEqual(panel.data["count"], 1)
        self.assertEqual(catalog.status_code, 400)

    def test_mine_reports_received_amount_and_total(self):
        sold = make_auction(self.seller, status=Auction.Status.SCHEDULED)
        place_bid(
            auction_id=sold.pk, bidder=self.alice, amount_cents=10_000
        )
        place_bid(
            auction_id=sold.pk, bidder=self.bob, amount_cents=11_000
        )
        self._expire(sold)
        settle_auction(sold.pk)

        unsold = make_auction(
            self.seller,
            status=Auction.Status.LIVE,
            ends_in=timedelta(minutes=-1),
        )
        settle_auction(unsold.pk)

        running = make_auction(
            self.seller,
            status=Auction.Status.LIVE,
            ends_in=timedelta(hours=2),
        )

        self._auth(self.seller)
        response = self.client.get(f"{self.url}mine/")

        rows = {row["id"]: row for row in response.data["results"]}

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(rows[sold.pk]["received_cents"], 11_000)
        self.assertEqual(rows[unsold.pk]["received_cents"], 0)
        self.assertIsNone(rows[running.pk]["received_cents"])
        self.assertEqual(
            response.data["summary"]["total_received_cents"], 11_000
        )


class AuctionWonTests(APITestCase):

    def setUp(self):
        self.seller = make_user(
            username="won_seller",
            email="won_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="won_alice", email="won_alice@example.com"
        )
        self.bob = make_user(username="won_bob", email="won_bob@example.com")

        fund(self.alice, 100_000)
        fund(self.bob, 100_000)

        self.url = "/api/auctions/won/"

    def _auth(self, user):
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def _auction(self):
        return make_auction(self.seller, status=Auction.Status.SCHEDULED)

    def _expire(self, auction):
        Auction.objects.filter(pk=auction.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )
        auction.refresh_from_db()

    def test_won_requires_authentication(self):
        self.client.credentials()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_won_is_empty_before_settlement(self):
        auction = self._auction()
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        place_bid(
            auction_id=auction.pk, bidder=self.bob, amount_cents=11_000
        )

        self._auth(self.bob)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)

    def test_won_lists_settled_wins_with_receipt(self):
        auction = self._auction()
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        place_bid(
            auction_id=auction.pk, bidder=self.bob, amount_cents=11_000
        )
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=12_000
        )
        self._expire(auction)
        settle_auction(auction.pk)

        receipt = Receipt.objects.get(auction=auction)

        self._auth(self.alice)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        row = response.data["results"][0]
        self.assertEqual(row["status"], Auction.Status.ENDED)
        self.assertEqual(row["winner_pseudonym"], pseudo(self.alice))
        self.assertEqual(
            row["receipt_public_uuid"], str(receipt.public_uuid)
        )
        self.assertEqual(row["seller_pseudonym"], pseudo(self.seller))
        self.assertNotIn("seller_id", row)
        self.assertNotIn("winner_id", row)

    def test_won_excludes_lots_i_lost(self):
        auction = self._auction()
        place_bid(
            auction_id=auction.pk, bidder=self.alice, amount_cents=10_000
        )
        place_bid(
            auction_id=auction.pk, bidder=self.bob, amount_cents=11_000
        )
        self._expire(auction)
        settle_auction(auction.pk)

        self._auth(self.alice)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)


class StartPromotionTests(APITestCase):
    def setUp(self):
        self.seller = make_user(
            username="start_seller",
            email="start_seller@example.com",
            role=User.Role.AUCTIONEER,
        )

    def test_sweep_promotes_a_started_scheduled_auction(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)

        settled = settle_expired_auctions()

        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.LIVE)
        self.assertEqual(settled, 0)

    def test_sweep_stays_quiet_when_run_twice(self):
        auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)

        settle_expired_auctions()
        settled = settle_expired_auctions()

        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.LIVE)
        self.assertEqual(settled, 0)

    def test_sweep_leaves_future_live_ended_and_cancelled_lots_alone(self):
        future = make_auction(
            self.seller,
            status=Auction.Status.SCHEDULED,
            starts_in=timedelta(hours=2),
            ends_in=timedelta(hours=3),
        )
        live = make_auction(self.seller)
        ended = make_auction(self.seller, status=Auction.Status.ENDED)
        cancelled = make_auction(self.seller, status=Auction.Status.CANCELLED)

        settle_expired_auctions()

        for auction in (future, live, ended, cancelled):
            auction.refresh_from_db()

        self.assertEqual(future.status, Auction.Status.SCHEDULED)
        self.assertEqual(live.status, Auction.Status.LIVE)
        self.assertEqual(ended.status, Auction.Status.ENDED)
        self.assertEqual(cancelled.status, Auction.Status.CANCELLED)

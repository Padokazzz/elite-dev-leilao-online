from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from auctions.models import Auction
from catalog.models import AuctionItem
from wallets.models import Wallet, WalletTransaction
from wallets.services import deposit, get_or_create_wallet

from .exceptions import BidRejected
from .models import Bid
from .services import place_bid

from threading import Thread

from django.db import connections

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
    """Prova que o select_for_update serializa lances simultâneos.

    Sem TransactionTestCase as threads não enxergariam os dados do
    setUp nem o lock teria o mesmo efeito de produção.
    """

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
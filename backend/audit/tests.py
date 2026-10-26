from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APITestCase

from auctions.models import Auction
from bidding.models import Bid
from bidding.services import bid_hash, place_bid
from bidding.tests import fund, make_auction, make_user

from .services import pseudo

User = get_user_model()


class PseudonymTests(TestCase):

    def test_pseudonym_is_stable_for_the_same_user(self):
        user = make_user(username="pseudo_a", email="pseudo_a@example.com")

        self.assertEqual(pseudo(user), pseudo(user))

    def test_pseudonym_changes_when_the_secret_changes(self):
        user = make_user(username="pseudo_b", email="pseudo_b@example.com")

        original = pseudo(user)
        with override_settings(AUDIT_PSEUDO_SECRET="outro-segredo"):
            rotated = pseudo(user)

        self.assertNotEqual(original, rotated)

    def test_pseudonym_carries_no_identity(self):
        user = make_user(username="pseudo_c", email="pseudo_c@example.com")

        label = pseudo(user)

        self.assertNotIn(user.email, label)
        self.assertNotIn(user.username, label)
        self.assertRegex(label, r"^(Licitante|Leiloeiro) #[0-9a-f]{8}$")


class AuditChainTests(APITestCase):

    def setUp(self):
        self.seller = make_user(
            username="audit_seller",
            email="audit_seller@example.com",
            role=User.Role.AUCTIONEER,
        )
        self.alice = make_user(
            username="audit_alice", email="audit_alice@example.com"
        )
        self.bob = make_user(username="audit_bob", email="audit_bob@example.com")

        self.auction = make_auction(self.seller, status=Auction.Status.SCHEDULED)

        fund(self.alice, 100_000)
        fund(self.bob, 100_000)

        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=10_000
        )
        place_bid(
            auction_id=self.auction.pk, bidder=self.bob, amount_cents=11_000
        )
        place_bid(
            auction_id=self.auction.pk, bidder=self.alice, amount_cents=12_000
        )

        self.url = f"/api/auctions/{self.auction.pk}/audit/"

    def test_fresh_chain_is_intact_and_links_every_row(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["intact"])
        self.assertIsNone(response.data["tampered"])

        chain = response.data["chain"]

        self.assertEqual([row["seq"] for row in chain], [1, 2, 3])
        self.assertEqual(chain[0]["prev_hash"], "0" * 64)

        for older, newer in zip(chain, chain[1:]):
            self.assertEqual(newer["prev_hash"], older["hash"])

    def test_hash_covers_every_field(self):
        now = timezone.now()
        base_kwargs = {
            "prev_hash": "0" * 64,
            "auction_id": 1,
            "seq": 1,
            "bidder_id": 1,
            "amount_cents": 100,
            "accepted_at": now,
        }
        base = bid_hash(**base_kwargs)

        for field, value in {
            "prev_hash": "1" * 64,
            "auction_id": 2,
            "seq": 2,
            "bidder_id": 2,
            "amount_cents": 101,
            "accepted_at": now + timedelta(seconds=1),
        }.items():
            changed = {**base_kwargs, field: value}
            self.assertNotEqual(bid_hash(**changed), base, field)

    def test_raw_update_on_amount_is_caught_on_that_exact_line(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE bidding_bid SET amount_cents = 1 "
                "WHERE auction_id = %s AND seq = 2",
                [self.auction.pk],
            )

        response = self.client.get(self.url)

        self.assertFalse(response.data["intact"])
        self.assertEqual(response.data["tampered"]["seq"], 2)
        self.assertEqual(response.data["tampered"]["reason"], "hash_mismatch")
        self.assertEqual(len(response.data["chain"]), 1)

    def test_a_deleted_bid_is_caught_by_the_next_line(self):
        Bid.objects.filter(auction=self.auction, seq=2).delete()

        response = self.client.get(self.url)

        self.assertFalse(response.data["intact"])
        self.assertEqual(response.data["tampered"]["seq"], 3)
        self.assertEqual(response.data["tampered"]["reason"], "sequence_gap")

    def test_audit_is_public_and_hides_identity(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        body = str(response.data)
        for user in (self.alice, self.bob, self.seller):
            self.assertNotIn(user.email, body)
        self.assertNotIn("@", body)
        self.assertRegex(
            response.data["chain"][0]["bidder"], r"^Licitante #[0-9a-f]{8}$"
        )

    def test_unknown_auction_returns_404(self):
        response = self.client.get("/api/auctions/999999/audit/")

        self.assertEqual(response.status_code, 404)

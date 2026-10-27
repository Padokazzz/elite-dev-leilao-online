from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework import status
from rest_framework.test import APITestCase

from .exceptions import LedgerImmutableError
from .models import Wallet, WalletTransaction
from .services import (
    MAX_DEPOSIT_CENTS,
    MIN_DEPOSIT_CENTS,
    deposit,
    get_or_create_wallet,
)

User = get_user_model()


class WalletModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="bidder_one",
            email="bidder1@example.com",
            password="Strong-Password!2026",
        )
        self.wallet = Wallet.objects.create(user=self.user)

    def test_new_wallet_starts_empty(self):
        self.assertEqual(self.wallet.balance_cents, 0)
        self.assertEqual(self.wallet.committed_cents, 0)
        self.assertEqual(self.wallet.available_cents, 0)

    def test_available_cents_is_always_derived_from_columns(self):
        self.wallet.balance_cents = 50_000
        self.wallet.committed_cents = 20_000

        # available_cents NÃO é coluna: nunca pode dessincronizar.
        self.assertEqual(self.wallet.available_cents, 30_000)

        self.wallet.committed_cents = 50_000
        self.assertEqual(self.wallet.available_cents, 0)

    def test_database_rejects_commitment_above_balance(self):
        self.wallet.balance_cents = 10_000
        self.wallet.committed_cents = 20_000

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.wallet.save()

    def test_database_rejects_a_negative_commitment(self):
        self.wallet.committed_cents = -1

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.wallet.save()

    def test_wallet_is_created_only_once_per_user(self):
        first = get_or_create_wallet(self.user)
        second = get_or_create_wallet(self.user)

        self.assertEqual(Wallet.objects.filter(user=self.user).count(), 1)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.pk, self.wallet.pk)


class DepositServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="bidder_two",
            email="bidder2@example.com",
            password="Strong-Password!2026",
        )
        self.wallet = get_or_create_wallet(self.user)

    def test_deposit_increases_balance_and_available(self):
        updated = deposit(wallet_id=self.wallet.pk, amount_cents=50_000)

        self.assertEqual(updated.balance_cents, 50_000)
        self.assertEqual(updated.committed_cents, 0)
        self.assertEqual(updated.available_cents, 50_000)

    def test_deposit_writes_exactly_one_ledger_row(self):
        deposit(wallet_id=self.wallet.pk, amount_cents=50_000)

        transactions = WalletTransaction.objects.filter(wallet=self.wallet)
        self.assertEqual(transactions.count(), 1)

        row = transactions.get()
        self.assertEqual(row.kind, WalletTransaction.Kind.DEPOSIT)
        self.assertEqual(row.delta_cents, 50_000)
        self.assertEqual(row.committed_delta_cents, 0)
        self.assertIsNone(row.auction)
        self.assertEqual(row.description, "Depósito simulado")

    def test_ledger_sum_matches_wallet_balance(self):
        for amount in (50_000, 10_000, 12_345):
            deposit(wallet_id=self.wallet.pk, amount_cents=amount)

        total = WalletTransaction.objects.filter(
            wallet=self.wallet
        ).aggregate(total=Sum("delta_cents"))["total"]

        self.wallet.refresh_from_db()
        self.assertEqual(total, self.wallet.balance_cents)
        self.assertEqual(self.wallet.balance_cents, 72_345)

    def test_rejects_deposit_below_minimum(self):
        for amount in (0, -100, MIN_DEPOSIT_CENTS - 1):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    deposit(wallet_id=self.wallet.pk, amount_cents=amount)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_cents, 0)
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_rejects_deposit_above_maximum(self):
        with self.assertRaises(ValueError):
            deposit(
                wallet_id=self.wallet.pk,
                amount_cents=MAX_DEPOSIT_CENTS + 1,
            )

        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_failed_ledger_write_rolls_back_the_balance(self):
        with patch(
            "wallets.services.WalletTransaction.objects.create",
            side_effect=RuntimeError("banco caiu"),
        ):
            with self.assertRaises(RuntimeError):
                deposit(wallet_id=self.wallet.pk, amount_cents=50_000)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_cents, 0)
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_deposit_rejects_wallet_that_does_not_exist(self):
        with self.assertRaises(Wallet.DoesNotExist):
            deposit(wallet_id=999_999, amount_cents=50_000)

class WalletEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="bidder_three",
            email="bidder3@example.com",
            password="Strong-Password!2026",
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.token.key}"
        )
        self.wallet_url = "/api/wallets/"
        self.deposit_url = "/api/wallets/deposit/"

    def test_requires_authentication(self):
        self.client.credentials()  # limpa o cabeçalho

        response = self.client.get(self.wallet_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_wallet_creates_it_on_first_access(self):
        self.assertEqual(Wallet.objects.filter(user=self.user).count(), 0)

        response = self.client.get(self.wallet_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["balance_cents"], 0)
        self.assertEqual(response.data["committed_cents"], 0)
        self.assertEqual(response.data["available_cents"], 0)
        self.assertEqual(Wallet.objects.filter(user=self.user).count(), 1)

    def test_deposit_returns_201_and_updated_wallet(self):
        response = self.client.post(
            self.deposit_url,
            {"amount": "50.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["balance_cents"], 5000)
        self.assertEqual(response.data["available_cents"], 5000)

    def test_deposit_accumulates_across_calls(self):
        for amount in ("10.00", "25.50", "4.25"):
            response = self.client.post(
                self.deposit_url, {"amount": amount}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(response.data["balance_cents"], 3975)

    def test_rejects_amount_below_minimum(self):
        response = self.client.post(
            self.deposit_url, {"amount": "0.00"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("amount", response.data)

    def test_rejects_more_than_two_decimal_places(self):
        response = self.client.post(
            self.deposit_url, {"amount": "50.123"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_non_numeric_amount(self):
        response = self.client.post(
            self.deposit_url, {"amount": "cinquenta"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_missing_amount(self):
        response = self.client.post(self.deposit_url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_response_never_exposes_balance_as_float(self):
        self.client.post(self.deposit_url, {"amount": "50.10"}, format="json")

        response = self.client.get(self.wallet_url)

        self.assertIsInstance(response.data["balance_cents"], int)
        self.assertNotIsInstance(response.data["balance_cents"], float)

    def test_body_cannot_overwrite_balance_directly(self):
        self.client.post(self.deposit_url, {"amount": "50.00"}, format="json")

        response = self.client.post(
            self.deposit_url,
            {"amount": "50.00", "balance_cents": 999999},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.wallet_refresh()
        self.assertEqual(self.wallet.balance_cents, 10000)

    def wallet_refresh(self):
        self.wallet = Wallet.objects.get(user=self.user)

    def test_transactions_endpoint_returns_ledger_rows(self):
        self.client.post(self.deposit_url, {"amount": "50.00"}, format="json")

        response = self.client.get("/api/wallets/transactions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        row = response.data["results"][0]
        self.assertEqual(row["kind"], "deposit")
        self.assertEqual(row["kind_label"], "Depósito")
        self.assertEqual(row["delta_cents"], 5000)


class LedgerImmutabilityTests(TestCase):
    """Prova que o ledger é append-only: não se edita nem se apaga."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="bidder_four",
            email="bidder4@example.com",
            password="Strong-Password!2026",
        )
        self.wallet = get_or_create_wallet(self.user)
        self.row = WalletTransaction.objects.create(
            wallet=self.wallet,
            kind=WalletTransaction.Kind.DEPOSIT,
            delta_cents=10_000,
            description="Depósito simulado",
        )

    def test_ledger_row_cannot_be_deleted(self):
        with self.assertRaises(LedgerImmutableError):
            self.row.delete()

        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_ledger_row_cannot_be_updated(self):
        self.row.delta_cents = 999_999

        with self.assertRaises(LedgerImmutableError):
            self.row.save()

        self.row.refresh_from_db()
        self.assertEqual(self.row.delta_cents, 10_000)


class DepositThrottleTests(APITestCase):
    """Regressão: o DRF só aplica o throttle se o VIEW declarar o escopo.

    ScopedRateThrottle lê `view.throttle_scope` e ignora o `scope` da
    subclasse (rest_framework/throttling.py:219). Sem o atributo no view,
    ele devolve True sempre — o limite some em silêncio e a suíte continua
    verde, porque nada afirma o 429.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="throttle_user",
            email="throttle@example.com",
            password="Strong-Password!2026",
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.token.key}"
        )
        self.deposit_url = "/api/wallets/deposit/"

    @patch(
        "rest_framework.throttling.ScopedRateThrottle.get_rate",
        return_value="2/min",
    )
    def test_deposit_endpoint_enforces_its_scope(self, _mock_get_rate):
        for _ in range(2):
            response = self.client.post(
                self.deposit_url,
                {"amount": "10.00"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            self.deposit_url,
            {"amount": "10.00"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
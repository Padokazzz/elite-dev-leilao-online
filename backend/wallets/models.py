from django.conf import settings
from django.db import models
from django.db.models import F, Q

from .exceptions import LedgerImmutableError


class Wallet(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallet",
    )
    balance_cents = models.PositiveBigIntegerField(default=0)
    committed_cents = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(committed_cents__lte=F("balance_cents")),
                name="wallet_committed_within_balance",
            ),
        ]

    def __str__(self) -> str:
        return f"Carteira de {self.user.email} ({self.available_cents}c livres)"

    @property
    def available_cents(self) -> int:
        return self.balance_cents - self.committed_cents


class WalletTransaction(models.Model):

    class Kind(models.TextChoices):
        DEPOSIT = "deposit", "Depósito"
        BID_HOLD = "bid_hold", "Retida de lance"
        BID_RELEASE = "bid_release", "Liberação de lance"
        SETTLEMENT = "settlement", "Liquidação"

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    auction = models.ForeignKey(
        "auctions.Auction",
        on_delete=models.PROTECT,
        related_name="wallet_transactions",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    delta_cents = models.BigIntegerField(default=0)
    committed_delta_cents = models.BigIntegerField(default=0)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.delta_cents}c"

    @property
    def available_delta_cents(self) -> int:
        return self.delta_cents - self.committed_delta_cents

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise LedgerImmutableError(
                "WalletTransaction é append-only: não pode ser editada."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise LedgerImmutableError(
            "WalletTransaction é append-only: não pode ser excluída."
        )
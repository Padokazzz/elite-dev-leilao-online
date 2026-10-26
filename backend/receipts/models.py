import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Receipt(models.Model):

    auction = models.OneToOneField(
        "auctions.Auction",
        on_delete=models.PROTECT,
        related_name="receipt",
    )
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="receipts_won",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="receipts_sold",
    )
    amount_cents = models.PositiveBigIntegerField()
    public_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    settled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-settled_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_cents__gt=0),
                name="receipt_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Comprovante {self.public_uuid}"

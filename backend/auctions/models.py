
from django.conf import settings
from django.db import models
from django.db.models import Q


class Auction(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Agendado"
        LIVE = "live", "Ao vivo"
        ENDED = "ended", "Encerrado"
        CANCELLED = "cancelled", "Cancelado"

    item = models.ForeignKey(
        "catalog.AuctionItem",
        on_delete=models.PROTECT,
        related_name="auctions",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="auctions_created",
        limit_choices_to={"role": "auctioneer"},
    )
    starting_bid_cents = models.PositiveBigIntegerField()
    minimum_increment_cents = models.PositiveBigIntegerField(default=100)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="auctions_won",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(starting_bid_cents__gt=0),
                name="auction_starting_bid_positive",
            ),
            models.CheckConstraint(
                condition=Q(minimum_increment_cents__gt=0),
                name="auction_increment_positive",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=models.F("starts_at")),
                name="auction_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.item.title} | {self.get_status_display()}"

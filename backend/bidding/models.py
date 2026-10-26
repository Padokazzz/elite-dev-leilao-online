from django.conf import settings
from django.db import models
from django.db.models import Q


class Bid(models.Model):
    """Um lance aceito. Imutável: lance aceito não se desfaz.

    seq é sequencial DENTRO do lote e é atribuído sob lock, garantindo
    uma ordem total que a auditoria vai usar depois (cadeia de hash).
    """

    auction = models.ForeignKey(
        "auctions.Auction",
        on_delete=models.PROTECT,
        related_name="bids",
    )
    bidder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bids",
    )
    amount_cents = models.PositiveBigIntegerField()
    seq = models.PositiveIntegerField()
    accepted_at = models.DateTimeField(auto_now_add=True)
    prev_hash = models.CharField(max_length=64, null=True, blank=True)
    hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["seq"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_cents__gt=0),
                name="bid_amount_positive",
            ),
            models.UniqueConstraint(
                fields=["auction", "seq"],
                name="unique_bid_seq_per_auction",
            ),
        ]
        indexes = [
            models.Index(fields=["auction", "seq"]),
        ]

    def __str__(self) -> str:
        return f"Lote {self.auction_id} #{self.seq} — {self.amount_cents}c"
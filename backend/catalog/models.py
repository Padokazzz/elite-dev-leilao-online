from django.db import models

class AuctionItem(models.Model):
    source = models.CharField(max_length=100)
    external_id = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                name="unique_external_catalog_item",
            ),
        ]

        ordering = ["title"]


    def __str__(self):
        return self.title
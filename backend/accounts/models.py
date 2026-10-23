from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Role(models.TextChoices):
        AUCTIONEER = "auctioneer", "Leiloeiro"
        BIDDER = "bidder", "Participante"

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.BIDDER
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]
import hashlib
import hmac

from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()

ROLE_LABELS = {
    User.Role.BIDDER: "Licitante",
    User.Role.AUCTIONEER: "Leiloeiro",
}


def pseudo(user) -> str:
    secret = settings.AUDIT_PSEUDO_SECRET.encode()
    digest = hmac.new(
        secret, str(user.pk).encode(), hashlib.sha256
    ).hexdigest()[:8]

    return f"{ROLE_LABELS[user.role]} #{digest}"

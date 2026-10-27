from rest_framework.permissions import BasePermission

from .models import User


class IsAuctioneer(BasePermission):
    message = "Somente leiloeiros podem gerenciar lotes."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.AUCTIONEER
        )

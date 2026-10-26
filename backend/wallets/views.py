from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Wallet
from .serializers import DepositSerializer, WalletSerializer
from .services import deposit, get_or_create_wallet


class WalletView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = get_or_create_wallet(request.user)

        return Response(
            WalletSerializer(wallet).data,
            status=status.HTTP_200_OK,
        )


class DepositView(APIView):

    permission_classes = [IsAuthenticated]
    # O DRF lê o escopo no VIEW (ScopedRateThrottle.allow_request), nunca
    # na subclasse: sem throttle_scope, o throttle devolve True sempre.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "wallet_deposit"

    def post(self, request):
        serializer = DepositSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        wallet = get_or_create_wallet(request.user)

        try:
            wallet = deposit(
                wallet_id=wallet.pk,
                amount_cents=serializer.validated_data["amount_cents"],
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            WalletSerializer(wallet).data,
            status=status.HTTP_201_CREATED,
        )


class WalletTransactionsView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = get_or_create_wallet(request.user)

        rows = wallet.transactions.all()[:50]

        data = [
            {
                "kind": row.kind,
                "kind_label": row.get_kind_display(),
                "delta_cents": row.delta_cents,
                "committed_delta_cents": row.committed_delta_cents,
                "description": row.description,
                "auction_id": row.auction_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]

        return Response({"results": data}, status=status.HTTP_200_OK)

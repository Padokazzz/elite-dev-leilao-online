from decimal import Decimal

from rest_framework import serializers

from .models import Wallet


class WalletSerializer(serializers.ModelSerializer):

    available_cents = serializers.IntegerField(read_only=True)

    class Meta:
        model = Wallet
        fields = (
            "balance_cents",
            "committed_cents",
            "available_cents",
            "updated_at",
        )
        read_only_fields = fields


class DepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    def validate(self, attrs):
        amount = attrs["amount"]
        attrs["amount_cents"] = int(amount * 100)
        return attrs
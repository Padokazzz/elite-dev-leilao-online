from django.utils import timezone
from rest_framework import serializers

from catalog.models import AuctionItem

from .models import Auction


class AuctionCreateSerializer(serializers.ModelSerializer):
    item_id = serializers.PrimaryKeyRelatedField(
        source="item",
        queryset=AuctionItem.objects.all(),
    )
    status = serializers.ChoiceField(
        choices=[Auction.Status.SCHEDULED],
        default=Auction.Status.SCHEDULED,
    )

    class Meta:
        model = Auction
        fields = [
            "item_id",
            "starting_bid_cents",
            "minimum_increment_cents",
            "starts_at",
            "ends_at",
            "status",
        ]

    def validate_starting_bid_cents(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "O lance inicial deve ser maior que zero."
            )
        return value

    def validate_minimum_increment_cents(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "O incremento mínimo deve ser maior que zero."
            )
        return value

    def validate(self, attrs):
        starts_at = attrs.get(
            "starts_at", getattr(self.instance, "starts_at", None)
        )
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))

        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "O fim deve ser depois do início."}
            )

        if ends_at and ends_at <= timezone.now():
            raise serializers.ValidationError(
                {"ends_at": "O fim já passou."}
            )

        return attrs

    def create(self, validated_data):
        return Auction.objects.create(**validated_data)


class AuctionScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Auction
        fields = ["starts_at", "ends_at"]

    def validate(self, attrs):
        starts_at = attrs.get(
            "starts_at", getattr(self.instance, "starts_at", None)
        )
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))

        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "O fim deve ser depois do início."}
            )

        return attrs

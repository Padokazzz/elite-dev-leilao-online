from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import pseudo

from .models import Receipt


class ReceiptDetailView(APIView):

    permission_classes = [AllowAny]

    def get(self, request, public_uuid):
        receipt = get_object_or_404(
            Receipt.objects.select_related("auction__item", "winner", "seller"),
            public_uuid=public_uuid,
        )

        return Response(
            {
                "public_uuid": receipt.public_uuid,
                "auction_id": receipt.auction_id,
                "item_title": receipt.auction.item.title,
                "amount_cents": receipt.amount_cents,
                "settled_at": receipt.settled_at,
                "winner": pseudo(receipt.winner),
                "seller": pseudo(receipt.seller),
            },
            status=status.HTTP_200_OK,
        )

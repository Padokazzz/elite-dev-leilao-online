from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from auctions.models import Auction

from .services import verify_chain


class AuctionAuditView(APIView):

    permission_classes = [AllowAny]

    def get(self, request, auction_id: int):
        auction = get_object_or_404(Auction, pk=auction_id)

        return Response(verify_chain(auction), status=status.HTTP_200_OK)

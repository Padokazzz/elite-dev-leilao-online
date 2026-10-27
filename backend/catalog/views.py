from django.db import DatabaseError, transaction

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsAuctioneer
from .models import AuctionItem
from .serializers import ArtworkImportSerializer, ArtworkSearchSerializer
from .services import (
    SOURCE_NAME,
    ArtworkAPIError,
    get_artwork,
    search_artworks,
)


class CatalogSearchThrottle(AnonRateThrottle):
    scope = "catalog_search"


class ArtworkSearchView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [CatalogSearchThrottle]

    def get(self, request):
        serializer = ArtworkSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        try:
            artworks = search_artworks(
                query=serializer.validated_data["q"],
                limit=serializer.validated_data["limit"],
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ArtworkAPIError:
            return Response(
                {"detail": "O catálogo externo está temporariamente indisponível."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"results": artworks}, status=status.HTTP_200_OK)


class ArtworkImportView(APIView):
    permission_classes = [IsAuthenticated, IsAuctioneer]

    def post(self, request):
        serializer = ArtworkImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        external_id = serializer.validated_data["external_id"]

        try:
            artwork = get_artwork(external_id)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ArtworkAPIError:
            return Response(
                {"detail": "Não foi possível consultar a obra no catálogo externo."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            with transaction.atomic():
                item, created = AuctionItem.objects.update_or_create(
                    source=SOURCE_NAME,
                    external_id=artwork["id"],
                    defaults={
                        "title": artwork["title"],
                        "description": artwork["description"],
                        "image_url": artwork["image_url"],
                        "attributes": artwork["attributes"],
                    },
                )
        except DatabaseError:
            return Response(
                {"detail": "Não foi possível salvar a obra no catálogo."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "id": item.id,
                "source": item.source,
                "external_id": item.external_id,
                "title": item.title,
                "description": item.description,
                "image_url": item.image_url,
                "attributes": item.attributes,
                "created": created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

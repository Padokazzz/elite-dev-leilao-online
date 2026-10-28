from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import AuctionItem
from .services import ArtworkAPIError, SOURCE_NAME
from unittest.mock import MagicMock, patch

from catalog.services import (
    MAX_RESPONSE_BYTES,
    ArtworkAPIError,
    _normalize_artwork,
    _request_json,
)


User = get_user_model()


class CatalogEndpointTests(APITestCase):
    def setUp(self):
        cache.clear()

        self.auctioneer = User.objects.create_user(
            username="auctioneer",
            email="auctioneer@example.com",
            password="Strong-Password!2026",
            role=User.Role.AUCTIONEER,
        )
        self.bidder = User.objects.create_user(
            username="bidder",
            email="bidder@example.com",
            password="Strong-Password!2026",
            role=User.Role.BIDDER,
        )

    def authenticate_as(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {token.key}"
        )

    @patch("catalog.views.search_artworks")
    def test_search_returns_external_results(self, mock_search):
        mock_search.return_value = [
            {
                "id": "123",
                "title": "Artwork Example",
                "description": "",
                "image_url": "https://example.com/artwork.jpg",
                "image_id": "abc-123",
                "attributes": {"artist": "Unknown"},
            }
        ]

        response = self.client.get(
            "/api/catalog/search/",
            {"q": "painting", "limit": 5},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["title"],
            "Artwork Example",
        )
        self.assertEqual(
            response.data["results"][0]["image_id"],
            "abc-123",
        )
        mock_search.assert_called_once_with(query="painting", limit=5)

    def test_search_requires_query(self):
        response = self.client.get("/api/catalog/search/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_rejects_limit_above_maximum(self):
        response = self.client.get(
            "/api/catalog/search/",
            {"q": "painting", "limit": 21},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch(
        "catalog.views.search_artworks",
        side_effect=ArtworkAPIError("API indisponível"),
    )
    def test_search_returns_bad_gateway_when_external_api_fails(
        self, mock_search
    ):
        response = self.client.get(
            "/api/catalog/search/",
            {"q": "painting"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_502_BAD_GATEWAY,
        )

    def test_import_requires_authentication(self):
        response = self.client.post(
            "/api/catalog/import/",
            {"external_id": "123"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    @patch("catalog.views.get_artwork")
    def test_bidder_cannot_import_artwork(self, mock_get_artwork):
        self.authenticate_as(self.bidder)

        response = self.client.post(
            "/api/catalog/import/",
            {"external_id": "123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_artwork.assert_not_called()

    @patch("catalog.views.get_artwork")
    def test_auctioneer_imports_artwork(self, mock_get_artwork):
        self.authenticate_as(self.auctioneer)
        mock_get_artwork.return_value = {
            "id": "123",
            "title": "Artwork Example",
            "description": "Example description",
            "image_url": "https://example.com/artwork.jpg",
            "attributes": {"artist": "Example Artist"},
        }

        response = self.client.post(
            "/api/catalog/import/",
            {"external_id": "123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["created"])
        self.assertEqual(AuctionItem.objects.count(), 1)
        self.assertEqual(AuctionItem.objects.get().external_id, "123")

    @patch("catalog.views.get_artwork")
    def test_importing_same_artwork_again_does_not_duplicate_it(
        self, mock_get_artwork
    ):
        self.authenticate_as(self.auctioneer)
        mock_get_artwork.return_value = {
            "id": "123",
            "title": "Updated Artwork Title",
            "description": "",
            "image_url": "",
            "attributes": {"artist": "Example Artist"},
        }

        first_response = self.client.post(
            "/api/catalog/import/",
            {"external_id": "123"},
            format="json",
        )
        second_response = self.client.post(
            "/api/catalog/import/",
            {"external_id": "123"},
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertFalse(second_response.data["created"])
        self.assertEqual(AuctionItem.objects.count(), 1)
        self.assertEqual(
            AuctionItem.objects.get().title,
            "Updated Artwork Title",
        )

    @patch(
        "catalog.views.get_artwork",
        side_effect=ArtworkAPIError("API indisponível"),
    )
    def test_import_returns_bad_gateway_when_external_api_fails(
        self, mock_get_artwork
    ):
        self.authenticate_as(self.auctioneer)

        response = self.client.post(
            "/api/catalog/import/",
            {"external_id": "123"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_502_BAD_GATEWAY,
        )
        self.assertEqual(AuctionItem.objects.count(), 0)

    @patch(
        "catalog.views.get_artwork",
        side_effect=ValueError("Somente obras em domínio público"),
    )
    def test_import_rejects_artwork_outside_public_domain(
        self, mock_get_artwork
    ):
        self.authenticate_as(self.auctioneer)

        response = self.client.post(
            "/api/catalog/import/",
            {"external_id": "123"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(AuctionItem.objects.count(), 0)

    def test_import_rejects_non_numeric_external_id(self):
        self.authenticate_as(self.auctioneer)

        response = self.client.post(
            "/api/catalog/import/",
            {"external_id": "abc"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AuctionItem.objects.count(), 0)

class ArtworkServiceTests(APITestCase):
    def test_normalize_artwork_builds_official_image_url(self):
        artwork = {
            "id": 123,
            "title": "Water Lilies",
            "image_id": "abc-123",
            "is_public_domain": True,
            "artist_display": "Claude Monet",
        }

        result = _normalize_artwork(artwork)

        self.assertEqual(result["id"], "123")
        self.assertEqual(result["title"], "Water Lilies")
        self.assertEqual(
            result["image_url"],
            "https://www.artic.edu/iiif/2/abc-123/full/843,/0/default.jpg",
        )
        self.assertEqual(result["image_id"], "abc-123")
        self.assertTrue(result["attributes"]["is_public_domain"])

    def test_normalize_artwork_rejects_invalid_identifier(self):
        with self.assertRaises(ArtworkAPIError):
            _normalize_artwork({
                "id": -1,
                "title": "Artwork",
            })

    def test_normalize_artwork_ignores_malformed_image_id(self):
        result = _normalize_artwork({
            "id": 123,
            "title": "Artwork",
            "image_id": "../unexpected/path",
        })

        self.assertEqual(result["image_url"], "")
        self.assertEqual(result["image_id"], "")

    def test_normalize_artwork_strips_html_from_description(self):
        result = _normalize_artwork({
            "id": 123,
            "title": "Artwork",
            "description": (
                "<p>In <em>Ferris Bueller's Day Off</em>, "
                "the artist &amp; friends &hellip;</p>\n"
                "<p>A second paragraph.</p>"
            ),
        })

        self.assertEqual(
            result["description"],
            "In Ferris Bueller's Day Off, the artist & friends … "
            "A second paragraph.",
        )
        self.assertNotIn("<", result["description"])

    @patch("catalog.services.urlopen")
    def test_request_json_rejects_oversized_response(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b"x" * (MAX_RESPONSE_BYTES + 1)
        )
        mock_urlopen.return_value.__enter__.return_value = response.__enter__.return_value

        with self.assertRaises(ArtworkAPIError):
            _request_json("https://api.artic.edu/api/v1/artworks/123")


class ArtworkImageViewTests(APITestCase):
    def _item(self, image_url):
        return AuctionItem.objects.create(
            source="artic",
            external_id="img-test",
            title="Obra",
            image_url=image_url,
        )

    @patch("catalog.views.fetch_artwork_image")
    def test_serves_stored_image(self, mock_fetch):
        mock_fetch.return_value = ("image/jpeg", b"\xff\xd8\xff\xe0fake")
        item = self._item(
            "https://www.artic.edu/iiif/2/abc/full/843,/0/default.jpg"
        )

        response = self.client.get(f"/api/catalog/image/{item.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response.content, b"\xff\xd8\xff\xe0fake")
        self.assertEqual(response["Cache-Control"], "public, max-age=86400")

    @patch("catalog.views.fetch_artwork_image")
    def test_returns_404_when_item_has_no_image(self, mock_fetch):
        item = self._item("")

        response = self.client.get(f"/api/catalog/image/{item.pk}/")

        self.assertEqual(response.status_code, 404)
        mock_fetch.assert_not_called()

    def test_returns_404_for_unknown_item(self):
        response = self.client.get("/api/catalog/image/999999/")

        self.assertEqual(response.status_code, 404)

    @patch("catalog.views.fetch_artwork_image")
    def test_returns_502_when_upstream_fails(self, mock_fetch):
        mock_fetch.side_effect = ArtworkAPIError("rede")
        item = self._item(
            "https://www.artic.edu/iiif/2/abc/full/843,/0/default.jpg"
        )

        response = self.client.get(f"/api/catalog/image/{item.pk}/")

        self.assertEqual(response.status_code, 502)


class ArtworkPreviewImageViewTests(APITestCase):
    @patch("catalog.views.fetch_artwork_image")
    def test_serves_preview_for_valid_image_id(self, mock_fetch):
        mock_fetch.return_value = ("image/jpeg", b"\xff\xd8\xff\xe0fake")

        response = self.client.get(
            "/api/catalog/preview/abc-123/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response.content, b"\xff\xd8\xff\xe0fake")
        self.assertEqual(response["Cache-Control"], "public, max-age=86400")
        mock_fetch.assert_called_once_with(
            "https://www.artic.edu/iiif/2/abc-123/full/400,/0/default.jpg"
        )

    def test_rejects_image_id_with_unsafe_characters(self):
        for bad_id in ("a b", "a.b", "ab%2Fcd", "x" * 101):
            with self.subTest(image_id=bad_id):
                response = self.client.get(
                    f"/api/catalog/preview/{bad_id}/"
                )

                self.assertEqual(response.status_code, 404)

    @patch("catalog.views.fetch_artwork_image")
    def test_returns_502_when_upstream_fails(self, mock_fetch):
        mock_fetch.side_effect = ArtworkAPIError("rede")

        response = self.client.get(
            "/api/catalog/preview/abc-123/"
        )

        self.assertEqual(response.status_code, 502)

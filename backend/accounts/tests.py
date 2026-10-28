from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.db import IntegrityError, transaction

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.settings import api_settings
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .serializers import RegisterSerializer


User = get_user_model()


class RegisterSerializerTests(TestCase):
    def setUp(self):
        self.valid_data = {
            "username": "test_bidder",
            "email": "bidder@example.com",
            "password": "N3ver-Use-This-Password!2026",
        }

    def test_registers_user_with_hashed_password(self):
        serializer = RegisterSerializer(data=self.valid_data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertEqual(user.email, "bidder@example.com")
        self.assertEqual(user.role, User.Role.BIDDER)
        self.assertTrue(user.check_password(self.valid_data["password"]))
        self.assertNotEqual(user.password, self.valid_data["password"])

    def test_normalizes_email_to_lowercase(self):
        data = {
            **self.valid_data,
            "email": "BIDDER@EXAMPLE.COM",
        }
        serializer = RegisterSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["email"], "bidder@example.com")

    def test_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            username="existing_bidder",
            email="bidder@example.com",
            password="Another-Strong-Password!2026",
        )
        data = {
            **self.valid_data,
            "email": "BIDDER@EXAMPLE.COM",
        }
        serializer = RegisterSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

    def test_rejects_invalid_email(self):
        data = {**self.valid_data, "email": "not-an-email"}
        serializer = RegisterSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

    def test_rejects_short_password(self):
        data = {**self.valid_data, "password": "123"}
        serializer = RegisterSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)

    def test_rejects_weak_password(self):
        data = {**self.valid_data, "password": "password"}
        serializer = RegisterSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)

    def test_public_registration_can_choose_the_auctioneer_role(self):
        data = {**self.valid_data, "role": User.Role.AUCTIONEER}
        serializer = RegisterSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertEqual(user.role, User.Role.AUCTIONEER)

    def test_public_registration_rejects_unknown_role(self):
        data = {**self.valid_data, "role": "superadmin"}
        serializer = RegisterSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("role", serializer.errors)

    def test_password_is_not_returned_in_serialized_data(self):
        serializer = RegisterSerializer(data=self.valid_data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertNotIn("password", serializer.data)
        self.assertEqual(user.role, User.Role.BIDDER)

class UserEmailConstraintTests(TestCase):
    def test_database_rejects_duplicate_email_with_different_case(self):
        User.objects.create_user(
            username="first_user",
            email="unique@example.com",
            password="Strong-Password!2026",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    username="second_user",
                    email="UNIQUE@EXAMPLE.COM",
                    password="Another-Strong-Password!2026",
                )

class RegisterEndpointTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.url = "/api/auth/register/"
        self.valid_data = {
            "username": "new_bidder",
            "email": "NEW_BIDDER@example.com",
            "password": "Strong-Password!2026",
        }

    def test_registers_user_and_returns_created(self):
        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            User.objects.filter(email="new_bidder@example.com").exists()
        )
        self.assertNotIn("password", response.data)
        self.assertEqual(response.data["role"], User.Role.BIDDER)

    def test_rejects_invalid_email(self):
        data = {**self.valid_data, "email": "invalid-email"}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_weak_password(self):
        data = {**self.valid_data, "password": "password"}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            username="existing_bidder",
            email="new_bidder@example.com",
            password="Another-Strong-Password!2026",
        )

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_public_registration_can_choose_the_auctioneer_role(self):
        data = {**self.valid_data, "role": User.Role.AUCTIONEER}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="new_bidder@example.com")
        self.assertEqual(user.role, User.Role.AUCTIONEER)

    def test_public_registration_rejects_unknown_role(self):
        data = {**self.valid_data, "role": "superadmin"}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("role", response.data)


class LoginEndpointTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="leonardo",
            email="leonardo@example.com",
            password="SenhaForte!2026",
        )
        self.url = "/api/auth/login/"

    def test_login_with_valid_credentials_returns_token_and_user(self):
        response = self.client.post(
            self.url,
            {
                "email": "LEONARDO@example.com",
                "password": "SenhaForte!2026",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        self.assertEqual(response.data["user"]["email"], self.user.email)
        self.assertNotIn("password", response.data["user"])

    def test_login_with_wrong_password_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "email": self.user.email,
                "password": "SenhaErrada!2026",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn("token", response.data)

    def test_login_with_unknown_email_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "email": "inexistente@example.com",
                "password": "SenhaForte!2026",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn("token", response.data)

    def test_login_requires_email_and_password(self):
        response = self.client.post(
            self.url,
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            self.url,
            {
                "email": self.user.email,
                "password": "SenhaForte!2026",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertFalse(Token.objects.filter(user=self.user).exists())


class LoginThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.url = "/api/auth/login/"

    @patch(
        "accounts.views.LoginThrottle.get_rate",
        return_value="2/min",
    )
    def test_login_is_throttled_after_limit(self, mock_get_rate):
        cache.clear()

        for _ in range(2):
            response = self.client.post(
                self.url,
                {
                    "email": "naoexiste@example.com",
                    "password": "senha-incorreta",
                },
                format="json",
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
            )

        response = self.client.post(
            self.url,
            {
                "email": "naoexiste@example.com",
                "password": "senha-incorreta",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )


class ThrottleIdentTests(TestCase):
    class Probe(SimpleRateThrottle):
        rate = "1000/min"

    def test_settings_trust_exactly_one_proxy(self):
        self.assertEqual(api_settings.NUM_PROXIES, 1)

    def test_ident_uses_the_hop_the_trusted_proxy_added(self):
        request = RequestFactory().get(
            "/", HTTP_X_FORWARDED_FOR="203.0.113.7, 198.51.100.9"
        )

        self.assertEqual(
            self.Probe().get_ident(request), "198.51.100.9"
        )

    def test_ident_falls_back_to_the_remote_address(self):
        request = RequestFactory().get("/")

        self.assertEqual(self.Probe().get_ident(request), "127.0.0.1")


class MeEndpointTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="leonardo",
            email="leonardo@example.com",
            password="SenhaForte!2026",
        )
        self.url = "/api/auth/me/"

    def test_me_without_token_returns_401(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_me_with_valid_token_returns_user_data(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {token.key}"
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data["id"], self.user.id)
        self.assertEqual(
            response.data["username"],
            self.user.username,
        )
        self.assertEqual(
            response.data["email"],
            self.user.email,
        )
        self.assertEqual(response.data["role"], self.user.role)
        self.assertNotIn("password", response.data)

    def test_me_with_invalid_token_returns_401(self):
        self.client.credentials(
            HTTP_AUTHORIZATION="Token token-invalido"
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class LogoutEndpointTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="leonardo",
            email="leonardo@example.com",
            password="SenhaForte!2026",
        )
        self.token = Token.objects.create(user=self.user)
        self.url = "/api/auth/logout/"

    def test_logout_without_token_returns_401(self):
        response = self.client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_logout_deletes_token(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.token.key}"
        )

        response = self.client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertFalse(
            Token.objects.filter(user=self.user).exists()
        )

    def test_deleted_token_cannot_access_me_endpoint(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.token.key}"
        )

        logout_response = self.client.post(self.url)

        self.assertEqual(
            logout_response.status_code,
            status.HTTP_200_OK,
        )

        me_response = self.client.get("/api/auth/me/")

        self.assertEqual(
            me_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

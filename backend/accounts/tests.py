from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase
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

    def test_public_registration_cannot_assign_auctioneer_role(self):
        data = {**self.valid_data, "role": User.Role.AUCTIONEER}
        serializer = RegisterSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertEqual(user.role, User.Role.BIDDER)

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

    def test_public_registration_cannot_assign_auctioneer_role(self):
        data = {**self.valid_data, "role": User.Role.AUCTIONEER}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="new_bidder@example.com")
        self.assertEqual(user.role, User.Role.BIDDER)
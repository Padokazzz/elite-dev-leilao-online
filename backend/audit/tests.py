from django.test import TestCase, override_settings

from bidding.tests import make_user

from .services import pseudo


class PseudonymTests(TestCase):

    def test_pseudonym_is_stable_for_the_same_user(self):
        user = make_user(username="pseudo_a", email="pseudo_a@example.com")

        self.assertEqual(pseudo(user), pseudo(user))

    def test_pseudonym_changes_when_the_secret_changes(self):
        user = make_user(username="pseudo_b", email="pseudo_b@example.com")

        original = pseudo(user)
        with override_settings(AUDIT_PSEUDO_SECRET="outro-segredo"):
            rotated = pseudo(user)

        self.assertNotEqual(original, rotated)

    def test_pseudonym_carries_no_identity(self):
        user = make_user(username="pseudo_c", email="pseudo_c@example.com")

        label = pseudo(user)

        self.assertNotIn(user.email, label)
        self.assertNotIn(user.username, label)
        self.assertRegex(label, r"^(Licitante|Leiloeiro) #[0-9a-f]{8}$")

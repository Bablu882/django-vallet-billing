from decimal import Decimal
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import Wallet, Recharge, ConsultationSession, WalletTransaction
from .services import process_recharge_callback, assign_session, accept_session, start_session, bill_session

User = get_user_model()

class WalletBillingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="alice", password="strong-password-123", role=User.Role.USER)
        self.provider = User.objects.create_user(username="provider", password="strong-password-123", role=User.Role.PROVIDER)
        self.wallet = Wallet.objects.get(user=self.user)

    def recharge(self, amount):
        recharge = Recharge.objects.create(user=self.user, amount=Decimal(amount), reference=f"REF-{amount}-{Recharge.objects.count()}")
        return process_recharge_callback(recharge.reference, Recharge.Status.SUCCESS)

    def make_accepted_session(self, rate="10.00"):
        session = ConsultationSession.objects.create(user=self.user, provider=None, rate_per_minute=Decimal(rate))
        session = assign_session(session.id, self.provider)
        return accept_session(session.id, self.provider)

    def test_insufficient_balance_cannot_start(self):
        self.recharge("49.99")
        session = self.make_accepted_session("10.00")
        self.client.force_authenticate(self.user)
        response = self.client.post(f"/api/sessions/{session.id}/start/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("49.99"))

    def test_happy_path_two_minutes(self):
        self.recharge("100.00")
        session = self.make_accepted_session("10.00")
        session = start_session(session.id, self.user)
        # Simulate 2 minutes elapsed without waiting in real time.
        ConsultationSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(minutes=2, seconds=1))
        session = bill_session(session.id)
        self.assertEqual(session.billed_minutes, 2)
        self.assertEqual(session.total_charged, Decimal("20.00"))
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("80.00"))
        self.client.force_authenticate(self.user)
        response = self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_balance_runs_out_auto_ends_without_negative_balance(self):
        self.recharge("50.00")
        session = self.make_accepted_session("10.00")
        session = start_session(session.id, self.user)
        # Starting requires 5x rate; after start, set balance as if prior minutes were billed.
        Wallet.objects.filter(user=self.user).update(balance=Decimal("10.00"))
        ConsultationSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(minutes=3, seconds=1), billed_minutes=1, total_charged=Decimal("10.00"))
        session = bill_session(session.id)
        self.assertEqual(session.status, ConsultationSession.Status.COMPLETED)
        self.assertEqual(session.ended_by, ConsultationSession.EndedBy.SYSTEM)
        self.assertEqual(session.end_reason, "Insufficient balance for next minute")
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("0.00"))

    def test_invalid_transition_returns_400(self):
        session = self.make_accepted_session("10.00")
        self.client.force_authenticate(self.user)
        response = self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_duplicate_recharge_callback_credits_once(self):
        recharge = Recharge.objects.create(user=self.user, amount=Decimal("25.00"), reference="DUPLICATE-REF")
        process_recharge_callback(recharge.reference, Recharge.Status.SUCCESS)
        process_recharge_callback(recharge.reference, Recharge.Status.SUCCESS)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("25.00"))
        self.assertEqual(WalletTransaction.objects.filter(recharge=recharge).count(), 1)

    def test_duplicate_billing_does_not_charge_same_minute_twice(self):
        self.recharge("100.00")
        session = self.make_accepted_session("10.00")
        session = start_session(session.id, self.user)
        ConsultationSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(minutes=1, seconds=5))
        bill_session(session.id)
        bill_session(session.id)
        self.assertEqual(WalletTransaction.objects.filter(session=session, kind=WalletTransaction.Kind.SESSION_CHARGE).count(), 1)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, Decimal("90.00"))

    def test_register_creates_wallet(self):
        response = self.client.post("/api/auth/register/", {
            "username": "newuser", "email": "new@example.com", "password": "long-enough-password-123", "role": "USER"
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Wallet.objects.filter(user__username="newuser").exists())

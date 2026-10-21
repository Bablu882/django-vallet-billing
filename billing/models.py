import uuid
from decimal import Decimal
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

class User(AbstractUser):
    class Role(models.TextChoices):
        USER = "USER", "User"
        PROVIDER = "PROVIDER", "Provider"
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER, db_index=True)

class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}: {self.balance}"

class Recharge(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recharges")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.reference} ({self.status})"

class ConsultationSession(models.Model):
    class Status(models.TextChoices):
        UNASSIGNED = "unassigned", "Unassigned"
        ASSIGNED = "assigned", "Assigned"
        ACCEPTED = "accepted_by_provider", "Accepted by provider"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class EndedBy(models.TextChoices):
        USER = "user", "User"
        PROVIDER = "provider", "Provider"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="consultation_sessions")
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="provider_sessions")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.UNASSIGNED, db_index=True)
    rate_per_minute = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    fixed_rate_per_minute = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    billed_minutes = models.PositiveIntegerField(default=0)
    total_charged = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    ended_by = models.CharField(max_length=10, choices=EndedBy.choices, null=True, blank=True)
    end_reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user", "status"]), models.Index(fields=["provider", "status"])]

    @property
    def billable_seconds(self):
        if not self.started_at:
            return 0
        from django.utils import timezone
        finish = self.ended_at or timezone.now()
        return max(0, int((finish - self.started_at).total_seconds()))

class WalletTransaction(models.Model):
    class Kind(models.TextChoices):
        RECHARGE = "recharge", "Recharge"
        SESSION_CHARGE = "session_charge", "Session charge"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    recharge = models.OneToOneField(Recharge, null=True, blank=True, on_delete=models.PROTECT, related_name="wallet_transaction")
    session = models.ForeignKey(ConsultationSession, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions")
    minute_number = models.PositiveIntegerField(null=True, blank=True)
    description = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "minute_number"], condition=Q(kind="session_charge"), name="uniq_session_billed_minute"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="wallet_transaction_amount_positive"),
        ]
        ordering = ["created_at"]

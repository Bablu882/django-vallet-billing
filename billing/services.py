from decimal import Decimal
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Wallet, Recharge, ConsultationSession, WalletTransaction, User

CENT = Decimal("0.01")

def _locked_wallet(user_id):
    # Caller must be inside transaction.atomic().
    return Wallet.objects.select_for_update().get(user_id=user_id)

@transaction.atomic
def create_recharge(user, amount):
    wallet = _locked_wallet(user.id)
    # Unique random reference; callback is scoped by this reference.
    import uuid
    reference = f"MOCK-{uuid.uuid4().hex}"
    return Recharge.objects.create(user=user, amount=amount, reference=reference)

@transaction.atomic
def process_recharge_callback(reference, status):
    recharge = Recharge.objects.select_for_update().select_related("user").filter(reference=reference).first()
    if recharge is None:
        raise ValidationError({"reference": "Unknown recharge reference."})
    if recharge.status != Recharge.Status.PENDING:
        # Idempotent: duplicate callback with same status is a no-op. Conflicting final callback rejected.
        if recharge.status == status:
            return recharge
        raise ValidationError({"status": f"Recharge already finalized as {recharge.status}."})
    wallet = _locked_wallet(recharge.user_id)
    recharge.status = status
    recharge.completed_at = timezone.now()
    recharge.save(update_fields=["status", "completed_at"])
    if status == Recharge.Status.SUCCESS:
        wallet.balance = (wallet.balance + recharge.amount).quantize(CENT)
        wallet.save(update_fields=["balance", "updated_at"])
        WalletTransaction.objects.create(
            wallet=wallet, kind=WalletTransaction.Kind.RECHARGE, amount=recharge.amount,
            balance_after=wallet.balance, recharge=recharge, description=f"Mock recharge {reference}"
        )
    return recharge

@transaction.atomic
def assign_session(session_id, provider):
    session = ConsultationSession.objects.select_for_update().get(pk=session_id)
    if session.status != ConsultationSession.Status.UNASSIGNED:
        raise ValidationError({"status": "Only an unassigned session can be assigned."})
    if provider.role != User.Role.PROVIDER:
        raise ValidationError({"provider": "Only a provider account can be assigned."})
    session.provider = provider
    session.status = ConsultationSession.Status.ASSIGNED
    session.save(update_fields=["provider", "status", "updated_at"])
    return session

@transaction.atomic
def accept_session(session_id, provider):
    session = ConsultationSession.objects.select_for_update().get(pk=session_id)
    if session.provider_id != provider.id:
        raise ValidationError({"provider": "Only the assigned provider can accept this session."})
    if session.status != ConsultationSession.Status.ASSIGNED:
        raise ValidationError({"status": "Only assigned sessions can be accepted."})
    session.status = ConsultationSession.Status.ACCEPTED
    session.save(update_fields=["status", "updated_at"])
    return session

@transaction.atomic
def start_session(session_id, user):
    session = ConsultationSession.objects.select_for_update().get(pk=session_id)
    if session.user_id != user.id:
        raise ValidationError({"session": "Only the session owner can start this session."})
    if session.status != ConsultationSession.Status.ACCEPTED:
        raise ValidationError({"status": "Only an accepted session can be started."})
    wallet = _locked_wallet(user.id)
    rate = session.rate_per_minute
    required = (rate * Decimal("5")).quantize(CENT)
    if wallet.balance < required:
        raise ValidationError({"wallet": f"At least {required} is required to start this session."})
    if ConsultationSession.objects.select_for_update().filter(
        user_id=user.id, status=ConsultationSession.Status.IN_PROGRESS
    ).exclude(pk=session.pk).exists():
        raise ValidationError({"session": "You already have an active session."})
    now = timezone.now()
    session.status = ConsultationSession.Status.IN_PROGRESS
    session.started_at = now
    session.fixed_rate_per_minute = rate
    session.save(update_fields=["status", "started_at", "fixed_rate_per_minute", "updated_at"])
    return session

@transaction.atomic
def _end_session(session, ended_by, reason):
    session.status = ConsultationSession.Status.COMPLETED
    session.ended_at = timezone.now()
    session.ended_by = ended_by
    session.end_reason = reason
    session.save(update_fields=["status", "ended_at", "ended_by", "end_reason", "updated_at"])
    return session

@transaction.atomic
def end_session(session_id, actor, ended_by):
    session = ConsultationSession.objects.select_for_update().get(pk=session_id)
    if session.status != ConsultationSession.Status.IN_PROGRESS:
        raise ValidationError({"status": "Only an in-progress session can be ended."})
    if ended_by == ConsultationSession.EndedBy.USER and session.user_id != actor.id:
        raise ValidationError({"session": "Only the session owner can end it as user."})
    if ended_by == ConsultationSession.EndedBy.PROVIDER and session.provider_id != actor.id:
        raise ValidationError({"session": "Only the assigned provider can end it."})
    if ended_by not in (ConsultationSession.EndedBy.USER, ConsultationSession.EndedBy.PROVIDER):
        raise ValidationError({"ended_by": "Unsupported ending actor."})
    # Bill all fully elapsed minutes before finalizing.
    bill_session(session.id)
    session.refresh_from_db()
    if session.status == ConsultationSession.Status.IN_PROGRESS:
        session = _end_session(session, ended_by, "Ended by user" if ended_by == "user" else "Ended by provider")
    return session

@transaction.atomic
def bill_session(session_id, now=None):
    session = ConsultationSession.objects.select_for_update().select_related("user").get(pk=session_id)
    if session.status != ConsultationSession.Status.IN_PROGRESS:
        return session
    now = now or timezone.now()
    elapsed_seconds = max(0, int((now - session.started_at).total_seconds()))
    elapsed_whole_minutes = elapsed_seconds // 60
    wallet = _locked_wallet(session.user_id)
    rate = session.fixed_rate_per_minute or session.rate_per_minute

    while session.billed_minutes < elapsed_whole_minutes:
        next_minute = session.billed_minutes + 1
        if wallet.balance < rate:
            # End at the last successfully billed minute. Do not charge a partial minute.
            # Preserve actual elapsed duration in timestamps; billed_minutes records paid time.
            session.status = ConsultationSession.Status.COMPLETED
            session.ended_at = now
            session.ended_by = ConsultationSession.EndedBy.SYSTEM
            session.end_reason = "Insufficient balance for next minute"
            session.save(update_fields=["status", "ended_at", "ended_by", "end_reason", "updated_at"])
            return session
        wallet.balance = (wallet.balance - rate).quantize(CENT)
        wallet.save(update_fields=["balance", "updated_at"])
        session.billed_minutes = next_minute
        session.total_charged = (session.total_charged + rate).quantize(CENT)
        WalletTransaction.objects.create(
            wallet=wallet, kind=WalletTransaction.Kind.SESSION_CHARGE,
            amount=rate, balance_after=wallet.balance, session=session,
            minute_number=next_minute, description=f"Session {session.id}, minute {next_minute}"
        )
        session.save(update_fields=["billed_minutes", "total_charged", "updated_at"])
    return session

def cancel_session(session_id, user):
    with transaction.atomic():
        session = ConsultationSession.objects.select_for_update().get(pk=session_id)
        if session.user_id != user.id:
            raise ValidationError({"session": "Only the session owner can cancel this session."})
        if session.status not in (ConsultationSession.Status.UNASSIGNED, ConsultationSession.Status.ASSIGNED, ConsultationSession.Status.ACCEPTED):
            raise ValidationError({"status": "Only sessions not yet in progress can be cancelled."})
        session.status = ConsultationSession.Status.CANCELLED
        session.ended_at = timezone.now()
        session.ended_by = ConsultationSession.EndedBy.USER
        session.end_reason = "Cancelled before start"
        session.save(update_fields=["status", "ended_at", "ended_by", "end_reason", "updated_at"])
        return session

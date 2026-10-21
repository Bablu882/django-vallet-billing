from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from .models import Wallet, Recharge, ConsultationSession, WalletTransaction

User = get_user_model()

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=10, trim_whitespace=False)
    role = serializers.ChoiceField(choices=User.Role.choices, read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "password", "role")
        read_only_fields = ("id",)

    def create(self, validated_data):
        validated_data.pop("role", None)
        # Public registration can create ordinary users only. Provision providers through admin/invitation flow.
        user = User.objects.create_user(**validated_data, role=User.Role.USER)
        return user

class WalletSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    class Meta:
        model = Wallet
        fields = ("username", "balance", "updated_at")
        read_only_fields = fields

class RechargeCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))

class RechargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recharge
        fields = ("id", "amount", "reference", "status", "created_at", "completed_at")
        read_only_fields = fields

class RechargeCallbackSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=100)
    status = serializers.ChoiceField(choices=[Recharge.Status.SUCCESS, Recharge.Status.FAILED])

class SessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsultationSession
        fields = ("id", "provider", "rate_per_minute")
        read_only_fields = ("id",)
    def validate_provider(self, provider):
        if provider and provider.role != User.Role.PROVIDER:
            raise serializers.ValidationError("Selected account is not a provider.")
        return provider
    def validate_rate_per_minute(self, value):
        if value <= 0:
            raise serializers.ValidationError("Rate must be greater than zero.")
        return value

class SessionSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source="user.username", read_only=True)
    provider_username = serializers.CharField(source="provider.username", read_only=True)
    billable_seconds = serializers.IntegerField(read_only=True)
    class Meta:
        model = ConsultationSession
        fields = (
            "id", "user", "user_username", "provider", "provider_username", "status",
            "rate_per_minute", "fixed_rate_per_minute", "started_at", "ended_at",
            "billable_seconds", "billed_minutes", "total_charged", "ended_by",
            "end_reason", "created_at", "updated_at",
        )
        read_only_fields = fields

class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = ("id", "kind", "amount", "balance_after", "description", "minute_number", "created_at")
        read_only_fields = fields

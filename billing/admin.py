from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Wallet, Recharge, ConsultationSession, WalletTransaction

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Application role", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Application role", {"fields": ("role",)}),)
    list_display = ("username", "email", "role", "is_staff", "is_active")

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "updated_at")
    readonly_fields = ("balance", "updated_at")

@admin.register(Recharge)
class RechargeAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "amount", "status", "created_at")
    readonly_fields = ("id", "user", "amount", "reference", "status", "created_at", "completed_at")

@admin.register(ConsultationSession)
class ConsultationSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "provider", "status", "rate_per_minute", "billed_minutes", "total_charged")
    readonly_fields = ("id", "user", "provider", "status", "rate_per_minute", "fixed_rate_per_minute", "started_at", "ended_at", "billed_minutes", "total_charged", "ended_by", "end_reason", "created_at", "updated_at")

@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "wallet", "kind", "amount", "balance_after", "session", "minute_number")
    readonly_fields = [field.name for field in WalletTransaction._meta.fields]

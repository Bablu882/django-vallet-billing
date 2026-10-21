from django.urls import path
from .views import (
    WalletView, RechargeListCreateView, MockRechargeCallbackView, SessionListCreateView,
    ProviderSessionListView, SessionActionView, SessionDetailView, WalletTransactionListView,
)

urlpatterns = [
    path("wallet/", WalletView.as_view(), name="wallet"),
    path("wallet/recharges/", RechargeListCreateView.as_view(), name="recharges"),
    path("wallet/recharges/mock-callback/", MockRechargeCallbackView.as_view(), name="mock-recharge-callback"),
    path("wallet/transactions/", WalletTransactionListView.as_view(), name="wallet-transactions"),
    path("sessions/", SessionListCreateView.as_view(), name="sessions"),
    path("provider/sessions/", ProviderSessionListView.as_view(), name="provider-sessions"),
    path("sessions/<uuid:session_id>/", SessionDetailView.as_view(), name="session-detail"),
    path("sessions/<uuid:session_id>/<str:action>/", SessionActionView.as_view(), name="session-action"),
]

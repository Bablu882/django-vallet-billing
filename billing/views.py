from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Wallet, Recharge, ConsultationSession, WalletTransaction, User
from .permissions import IsUserRole, IsProviderRole
from .serializers import (
    RegisterSerializer, WalletSerializer, RechargeCreateSerializer, RechargeSerializer,
    RechargeCallbackSerializer, SessionCreateSerializer, SessionSerializer, WalletTransactionSerializer,
)
from .services import (
    create_recharge, process_recharge_callback, assign_session, accept_session,
    start_session, end_session, bill_session, cancel_session,
)

UserModel = get_user_model()

@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

class WalletView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        return Response(WalletSerializer(wallet).data)

class RechargeListCreateView(generics.ListCreateAPIView):
    serializer_class = RechargeSerializer
    permission_classes = [IsUserRole]
    def get_queryset(self):
        return Recharge.objects.filter(user=self.request.user).order_by("-created_at")
    def create(self, request, *args, **kwargs):
        serializer = RechargeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recharge = create_recharge(request.user, serializer.validated_data["amount"])
        return Response(RechargeSerializer(recharge).data, status=status.HTTP_201_CREATED)

class MockRechargeCallbackView(APIView):
    # In a real integration this endpoint must be protected by provider signature verification.
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        serializer = RechargeCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recharge = process_recharge_callback(**serializer.validated_data)
        return Response(RechargeSerializer(recharge).data)

class SessionListCreateView(generics.ListCreateAPIView):
    serializer_class = SessionSerializer
    permission_classes = [IsUserRole]
    def get_queryset(self):
        return ConsultationSession.objects.filter(user=self.request.user).select_related("user", "provider").order_by("-created_at")
    def create(self, request, *args, **kwargs):
        serializer = SessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = serializer.save(user=request.user, status=ConsultationSession.Status.UNASSIGNED)
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)

class ProviderSessionListView(generics.ListAPIView):
    serializer_class = SessionSerializer
    permission_classes = [IsProviderRole]
    def get_queryset(self):
        return ConsultationSession.objects.filter(Q(provider=self.request.user) | Q(status=ConsultationSession.Status.UNASSIGNED)).select_related("user", "provider").order_by("-created_at")

class SessionActionView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, session_id, action):
        session = ConsultationSession.objects.filter(pk=session_id).first()
        if not session:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        if action == "assign":
            if request.user.role != User.Role.USER:
                return Response({"detail": "Only a user can assign a provider."}, status=403)
            if request.data.get("provider_id") is None:
                return Response({"provider_id": "This field is required."}, status=400)
            provider = UserModel.objects.filter(pk=request.data.get("provider_id"), role=User.Role.PROVIDER).first()
            if not provider:
                return Response({"provider_id": "Provider not found."}, status=400)
            if session.user_id != request.user.id:
                return Response({"detail": "You do not own this session."}, status=403)
            session = assign_session(session.id, provider)
        elif action == "accept":
            if request.user.role != User.Role.PROVIDER:
                return Response({"detail": "Only providers can accept sessions."}, status=403)
            session = accept_session(session.id, request.user)
        elif action == "start":
            if request.user.role != User.Role.USER:
                return Response({"detail": "Only users can start sessions."}, status=403)
            session = start_session(session.id, request.user)
        elif action == "end":
            if request.user.role not in (User.Role.USER, User.Role.PROVIDER):
                return Response({"detail": "Unsupported role."}, status=403)
            ending_role = "user" if request.user.role == User.Role.USER else "provider"
            session = end_session(session.id, request.user, ending_role)
        elif action == "bill":
            if request.user.id not in (session.user_id, session.provider_id) and not request.user.is_staff:
                return Response({"detail": "You cannot bill this session."}, status=403)
            session = bill_session(session.id)
        elif action == "cancel":
            if request.user.role != User.Role.USER:
                return Response({"detail": "Only users can cancel sessions."}, status=403)
            session = cancel_session(session.id, request.user)
        else:
            return Response({"detail": "Unknown action."}, status=404)
        return Response(SessionSerializer(session).data)

class SessionDetailView(generics.RetrieveAPIView):
    serializer_class = SessionSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "session_id"
    def get_queryset(self):
        qs = ConsultationSession.objects.select_related("user", "provider")
        if self.request.user.is_staff:
            return qs
        return qs.filter(Q(user=self.request.user) | Q(provider=self.request.user))

class WalletTransactionListView(generics.ListAPIView):
    serializer_class = WalletTransactionSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return WalletTransaction.objects.filter(wallet__user=self.request.user).order_by("-created_at")

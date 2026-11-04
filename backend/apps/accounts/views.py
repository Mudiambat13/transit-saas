from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit import service as audit
from apps.audit.models import AuditLog

from .models import Membership, User
from .permissions import HasTenantPermission
from .serializers import CompanyProfileSerializer, LoginSerializer, UserSerializer, me_payload
from .tenancy import TenantModelViewSet, get_tenant


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        if not ser.is_valid():
            audit.log("auth.login_failed", email_hint=str(request.data.get("email", ""))[:3] + "***")
            return Response({"detail": "Email ou mot de passe incorrect.", "code": "invalid_credentials"}, status=401)
        user = ser.validated_data["user"]
        m = user.membership
        if not user.is_platform_admin and (m is None or not m.tenant.is_active):
            audit.log("auth.login_blocked", actor=user, tenant=m.tenant if m else None)
            return Response({"detail": "Compte sans compagnie active ou compagnie suspendue.", "code": "tenant_inactive"}, status=403)
        refresh = RefreshToken.for_user(user)
        audit.log("auth.login", actor=user, tenant=m.tenant if m else None)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "user": me_payload(user)})


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from rest_framework_simplejwt.serializers import TokenRefreshSerializer
        from rest_framework_simplejwt.exceptions import TokenError

        ser = TokenRefreshSerializer(data=request.data)
        try:
            ser.is_valid(raise_exception=True)
        except TokenError:
            return Response({"detail": "Session expirée.", "code": "token_invalid"}, status=401)
        return Response(ser.validated_data)


class LogoutView(APIView):
    def post(self, request):
        token = request.data.get("refresh")
        if token:
            try:
                # Sans app blacklist : on journalise la déconnexion ; le client supprime ses jetons.
                RefreshToken(token)
            except Exception:
                pass
        m = request.user.membership
        audit.log("auth.logout", actor=request.user, tenant=m.tenant if m else None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(me_payload(request.user))


class CompanyProfileView(APIView):
    permission_classes = [HasTenantPermission]

    def get_permissions(self):
        self.required_perm = "company.manage" if self.request.method in ("PATCH", "PUT") else None
        return super().get_permissions()

    def get(self, request):
        return Response(CompanyProfileSerializer(get_tenant(request), context={"request": request}).data)

    def patch(self, request):
        tenant = get_tenant(request)
        ser = CompanyProfileSerializer(tenant, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        audit.log("company.updated", actor=request.user, tenant=tenant, entity="Tenant", entity_id=tenant.id,
                  fields=list(request.data.keys()))
        return Response(ser.data)


class UserViewSet(TenantModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    required_perms = {"*": "user.manage"}
    search_fields = ["email", "full_name", "phone"]

    def get_queryset(self):
        tenant = get_tenant(self.request)
        return User.objects.filter(memberships__tenant=tenant).distinct().order_by("full_name")

    def perform_create(self, serializer):
        user = serializer.save()
        audit.log("user.created", actor=self.request.user, tenant=get_tenant(self.request), entity="User", entity_id=user.id)

    def perform_update(self, serializer):
        user = serializer.save()
        audit.log("user.updated", actor=self.request.user, tenant=get_tenant(self.request), entity="User", entity_id=user.id)

    def perform_destroy(self, instance):
        # Désactivation plutôt que suppression (traçabilité).
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        Membership.objects.filter(user=instance, tenant=get_tenant(self.request)).update(is_active=False)
        audit.log("user.deactivated", actor=self.request.user, tenant=get_tenant(self.request), entity="User", entity_id=instance.id)


class AuditLogListView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "report.view"

    def get(self, request):
        tenant = get_tenant(request)
        qs = AuditLog.objects.filter(tenant=tenant)
        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action__startswith=action)
        rows = qs.select_related("actor")[:200]
        return Response([{
            "id": r.id, "action": r.action, "entity": r.entity, "entity_id": r.entity_id,
            "actor": r.actor.email if r.actor else None, "metadata": r.metadata,
            "created_at": r.created_at,
        } for r in rows])

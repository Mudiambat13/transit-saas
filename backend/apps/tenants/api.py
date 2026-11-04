"""Administration centrale (Super Admin). Aucun accès métier aux données des compagnies."""
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership, Role, User
from apps.accounts.permissions import IsPlatformAdmin
from apps.audit import service as audit
from apps.audit.models import AuditLog

from .models import Plan, Subscription, Tenant, TenantStatus


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["id", "name", "price", "currency", "period", "max_agencies", "max_users",
                  "max_trips_per_month", "max_tickets_per_month"]


class TenantSerializer(serializers.ModelSerializer):
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all(), write_only=True, required=False)
    plan_name = serializers.SerializerMethodField()
    admin_email = serializers.EmailField(write_only=True, required=False)
    admin_full_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    admin_password = serializers.CharField(write_only=True, required=False)
    counts = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "status", "currency", "timezone", "contact_email", "contact_phone",
                  "address", "settings", "created_at", "plan", "plan_name", "admin_email", "admin_full_name",
                  "admin_password", "counts"]
        read_only_fields = ["id", "status", "created_at"]

    def get_plan_name(self, obj):
        p = obj.current_plan
        return p.name if p else None

    def get_counts(self, obj):
        return {
            "agencies": obj.agency_set.count() if hasattr(obj, "agency_set") else 0,
            "users": obj.memberships.filter(is_active=True).count(),
        }

    def validate_admin_password(self, value):
        validate_password(value)
        return value

    def validate_admin_email(self, value):
        if User.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError("Cet email est déjà utilisé.")
        return value.lower()

    @transaction.atomic
    def create(self, validated):
        plan = validated.pop("plan", None)
        email = validated.pop("admin_email", None)
        full_name = validated.pop("admin_full_name", "")
        password = validated.pop("admin_password", None)
        if not (email and password):
            raise serializers.ValidationError("L'email et le mot de passe de l'administrateur initial sont obligatoires.")
        tenant = Tenant.objects.create(**validated)
        if plan:
            Subscription.objects.create(tenant=tenant, plan=plan)
        user = User.objects.create_user(email=email, password=password, full_name=full_name)
        Membership.objects.create(user=user, tenant=tenant, role=Role.COMPANY_ADMIN)
        return tenant

    def update(self, instance, validated):
        plan = validated.pop("plan", None)
        for k in ("admin_email", "admin_full_name", "admin_password"):
            validated.pop(k, None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if plan and instance.current_plan != plan:
            instance.subscriptions.filter(status="ACTIVE").update(status="ENDED", ends_at=timezone.now())
            Subscription.objects.create(tenant=instance, plan=plan)
        return instance


class PlatformTenantViewSet(viewsets.ModelViewSet):
    permission_classes = [IsPlatformAdmin]
    queryset = Tenant.objects.all().order_by("-created_at")
    serializer_class = TenantSerializer
    search_fields = ["name", "slug"]
    http_method_names = ["get", "post", "patch", "head", "options"]  # pas de suppression physique

    def perform_create(self, serializer):
        serializer.save()
        audit.log("platform.tenant_created", actor=self.request.user, entity="Tenant", entity_id=serializer.instance.id)

    def perform_update(self, serializer):
        serializer.save()
        audit.log("platform.tenant_updated", actor=self.request.user, entity="Tenant", entity_id=serializer.instance.id)

    def _set_status(self, request, pk, status_value, action_name):
        tenant = self.get_object()
        tenant.status = status_value
        tenant.save(update_fields=["status"])
        audit.log(action_name, actor=request.user, entity="Tenant", entity_id=tenant.id,
                  reason=str(request.data.get("reason", ""))[:200])
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._set_status(request, pk, TenantStatus.SUSPENDED, "platform.tenant_suspended")

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        return self._set_status(request, pk, TenantStatus.ACTIVE, "platform.tenant_reactivated")


class PlanViewSet(viewsets.ModelViewSet):
    permission_classes = [IsPlatformAdmin]
    queryset = Plan.objects.all().order_by("price")
    serializer_class = PlanSerializer


class PlatformMetricsView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        from apps.boarding.models import BoardingEvent
        from apps.ticketing.models import Ticket
        from apps.trips.models import Trip

        now = timezone.now()
        month = {"created_at__year": now.year, "created_at__month": now.month}
        return Response({
            "tenants": Tenant.objects.aggregate(
                total=Count("id"), active=Count("id", filter=Q(status="ACTIVE")), suspended=Count("id", filter=Q(status="SUSPENDED"))),
            "users": User.objects.filter(is_platform_admin=False, is_active=True).count(),
            "trips_this_month": Trip.objects.filter(**month).count(),
            "tickets_this_month": Ticket.objects.filter(**month).count(),
            "boardings_this_month": BoardingEvent.objects.filter(result="VALIDATED", **month).count(),
        })


class PlatformAuditView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = AuditLog.objects.select_related("actor", "tenant")
        if request.query_params.get("tenant"):
            qs = qs.filter(tenant_id=request.query_params["tenant"])
        return Response([{
            "id": r.id, "action": r.action, "tenant": r.tenant.name if r.tenant else None,
            "actor": r.actor.email if r.actor else None, "entity": r.entity, "entity_id": r.entity_id,
            "created_at": r.created_at,
        } for r in qs[:200]])

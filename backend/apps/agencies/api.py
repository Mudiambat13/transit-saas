from rest_framework import serializers

from apps.accounts.serializers import _enforce_plan_limit
from apps.accounts.tenancy import TenantModelViewSet, get_tenant
from apps.audit import service as audit

from .models import Agency


class AgencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Agency
        fields = ["id", "name", "city", "address", "phone", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        tenant = get_tenant(self.context["request"])
        name = attrs.get("name")
        if name:
            qs = Agency.objects.filter(tenant=tenant, name__iexact=name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"name": "Une agence porte déjà ce nom."})
        if not self.instance:
            _enforce_plan_limit(tenant, "max_agencies", Agency.objects.filter(tenant=tenant).count(), "agences")
        return attrs


class AgencyViewSet(TenantModelViewSet):
    queryset = Agency.objects.all()
    serializer_class = AgencySerializer
    search_fields = ["name", "city"]
    required_perms = {"list": "trip.view", "retrieve": "trip.view", "*": "agency.manage"}

    def perform_create(self, serializer):
        super().perform_create(serializer)
        audit.log("agency.created", actor=self.request.user, tenant=get_tenant(self.request),
                  entity="Agency", entity_id=serializer.instance.id)

    def perform_destroy(self, instance):
        # Une agence avec des voyages n'est jamais supprimée : désactivation.
        if instance.trips.exists():
            instance.is_active = False
            instance.save(update_fields=["is_active"])
        else:
            instance.delete()
        audit.log("agency.removed", actor=self.request.user, tenant=get_tenant(self.request),
                  entity="Agency", entity_id=instance.id)

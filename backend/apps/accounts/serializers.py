from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from apps.agencies.models import Agency
from apps.tenants.models import Tenant

from .models import Membership, Role, User
from .permissions import ALL_PERMISSIONS, permissions_for
from .tenancy import TenantPrimaryKeyRelatedField


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(email=attrs["email"].lower(), password=attrs["password"])
        if not user or not user.is_active:
            raise serializers.ValidationError("Email ou mot de passe incorrect.")
        attrs["user"] = user
        return attrs


def me_payload(user):
    m = user.membership
    tenant = None
    if m:
        t = m.tenant
        tenant = {
            "id": t.id, "name": t.name, "slug": t.slug, "currency": t.currency,
            "timezone": t.timezone, "status": t.status, "settings": t.settings,
        }
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "is_platform_admin": user.is_platform_admin,
        "role": m.role if m else None,
        "agency_id": m.agency_id if m else None,
        "permissions": sorted(permissions_for(m)) if m and m.tenant.is_active else [],
        "tenant": tenant,
    }


class UserSerializer(serializers.ModelSerializer):
    """Utilisateur d'une compagnie (vue via son adhésion)."""

    role = serializers.ChoiceField(choices=Role.choices, write_only=True)
    agency = TenantPrimaryKeyRelatedField(queryset=Agency.objects.all(), required=False, allow_null=True, write_only=True)
    password = serializers.CharField(write_only=True, required=False)
    extra_permissions = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)
    revoked_permissions = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "is_active", "role", "agency", "password",
                  "extra_permissions", "revoked_permissions"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        m = self._membership(instance)
        data["role"] = m.role if m else None
        data["agency"] = m.agency_id if m else None
        data["extra_permissions"] = m.extra_permissions if m else []
        data["revoked_permissions"] = m.revoked_permissions if m else []
        return data

    def _membership(self, user):
        tenant = self.context["request"].user.membership.tenant
        return user.memberships.filter(tenant=tenant).first()

    def validate_email(self, value):
        value = value.lower()
        qs = User.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Cet email est déjà utilisé.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def _check_perm_lists(self, attrs):
        for key in ("extra_permissions", "revoked_permissions"):
            unknown = set(attrs.get(key, [])) - ALL_PERMISSIONS
            if unknown:
                raise serializers.ValidationError({key: f"Permissions inconnues : {', '.join(sorted(unknown))}"})

    @transaction.atomic
    def create(self, validated):
        self._check_perm_lists(validated)
        request = self.context["request"]
        tenant = request.user.membership.tenant
        _enforce_plan_limit(tenant, "max_users", Membership.objects.filter(tenant=tenant, is_active=True).count(), "utilisateurs")
        if not validated.get("password"):
            raise serializers.ValidationError({"password": "Le mot de passe est obligatoire."})
        role, agency = validated.pop("role"), validated.pop("agency", None)
        extra = validated.pop("extra_permissions", [])
        revoked = validated.pop("revoked_permissions", [])
        user = User.objects.create_user(**validated)
        Membership.objects.create(user=user, tenant=tenant, role=role, agency=agency,
                                  extra_permissions=extra, revoked_permissions=revoked)
        return user

    @transaction.atomic
    def update(self, instance, validated):
        self._check_perm_lists(validated)
        m = self._membership(instance)
        for key in ("role", "agency", "extra_permissions", "revoked_permissions"):
            if key in validated:
                setattr(m, key, validated.pop(key))
        m.save()
        password = validated.pop("password", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


def _enforce_plan_limit(tenant, field, current_count, label):
    plan = tenant.current_plan
    limit = getattr(plan, field, 0) if plan else 0
    if limit and current_count >= limit:
        raise serializers.ValidationError(f"Limite de l'offre atteinte ({limit} {label}). Contactez le support.")


class CompanyProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "status", "currency", "timezone", "logo", "contact_email",
                  "contact_phone", "address", "settings"]
        read_only_fields = ["id", "slug", "status"]

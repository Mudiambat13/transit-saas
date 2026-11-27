from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from apps.agencies.models import Agency
from apps.tenants.models import Tenant

from .models import Membership, Role, User
from .permissions import ALL_PERMISSIONS, permissions_for

# Rôles qu'un responsable d'agence peut créer/gérer dans son agence. Les rôles d'encadrement restent réservés à l'administrateur.
TEAM_ROLES = {Role.TICKET_AGENT, Role.BOARDING_AGENT, Role.DRIVER}
AGENCY_BOUND_ROLES = {Role.AGENCY_MANAGER, Role.TICKET_AGENT}
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

    def validate(self, attrs):
        """Règles de délégation : l'administrateur gère tout ; le responsable d'agence gère son équipe, rien de plus."""
        attrs = super().validate(attrs)
        request = self.context["request"]
        actor = request.user.membership
        is_admin = "user.manage" in permissions_for(actor)
        target = self._membership(self.instance) if self.instance else None
        role = attrs.get("role", target.role if target else None)
        agency = attrs["agency"] if "agency" in attrs else (target.agency if target else None)
        errors = {}
        if not is_admin:
            if actor.agency_id is None:
                raise serializers.ValidationError("Votre compte n'est rattaché à aucune agence : vous ne pouvez pas gérer d'utilisateurs.")
            if role not in TEAM_ROLES or (target and target.role not in TEAM_ROLES):
                errors["role"] = "Vous pouvez gérer uniquement les agents de billetterie, d'embarquement et les chauffeurs de votre agence."
            if "extra_permissions" in attrs or "revoked_permissions" in attrs:
                errors["extra_permissions"] = "Seul l'administrateur peut modifier les permissions."
            attrs["agency"] = agency = actor.agency  # toujours dans son agence, quoi qu'envoie le client
        elif role in AGENCY_BOUND_ROLES and agency is None:
            errors["agency"] = "L'agence est obligatoire pour ce rôle."
        if self.instance is not None and self.instance.pk == request.user.pk:
            # Pas d'auto-promotion ni d'auto-verrouillage.
            for key in ("role", "agency", "is_active", "extra_permissions", "revoked_permissions"):
                if key in attrs and attrs[key] != {"role": target.role, "agency": target.agency, "is_active": self.instance.is_active,
                                                   "extra_permissions": target.extra_permissions, "revoked_permissions": target.revoked_permissions}[key]:
                    errors[key] = "Vous ne pouvez pas modifier ce réglage sur votre propre compte."
        if target and target.role == Role.COMPANY_ADMIN and (role != Role.COMPANY_ADMIN or attrs.get("is_active") is False):
            ensure_another_admin(target.tenant, exclude_user=self.instance)
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

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
        if role == Role.DRIVER:  # fiche chauffeur liée d'office : le compte peut suivre ses voyages
            from apps.fleet.models import Driver
            Driver.objects.create(tenant=tenant, full_name=user.full_name or user.email, phone=user.phone, user=user)
        return user

    @transaction.atomic
    def update(self, instance, validated):
        self._check_perm_lists(validated)
        m = self._membership(instance)
        for key in ("role", "agency", "extra_permissions", "revoked_permissions"):
            if key in validated:
                setattr(m, key, validated.pop(key))
        if "is_active" in validated:  # réactiver un compte réactive aussi son adhésion, sinon il ne pourrait pas se connecter
            m.is_active = validated["is_active"]
        m.save()
        password = validated.pop("password", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


def ensure_another_admin(tenant, exclude_user):
    others = Membership.objects.filter(tenant=tenant, role=Role.COMPANY_ADMIN, is_active=True, user__is_active=True).exclude(user=exclude_user)
    if not others.exists():
        raise serializers.ValidationError("Il doit rester au moins un administrateur actif dans la compagnie.")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Mot de passe actuel incorrect."})
        validate_password(attrs["new_password"], user)
        return attrs


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

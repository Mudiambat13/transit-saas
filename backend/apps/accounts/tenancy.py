"""Isolation multi-tenant côté serveur.

Le tenant est TOUJOURS résolu depuis l'utilisateur authentifié (adhésion active),
jamais depuis un identifiant fourni par le client.
"""
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied

from .models import Role
from .permissions import HasTenantPermission


def get_tenant(request):
    m = request.user.membership
    if m is None:
        raise PermissionDenied("Aucune compagnie active n'est associée à ce compte.")
    return m.tenant


def scope_by_agency(qs, membership, field="agency"):
    """Restreint au périmètre d'agence pour les utilisateurs rattachés à une agence."""
    if membership.agency_id and membership.role != Role.COMPANY_ADMIN:
        return qs.filter(**{f"{field}_id": membership.agency_id})
    return qs


class TenantPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Clé étrangère dont le queryset est automatiquement filtré sur le tenant de la requête :
    deviner l'identifiant d'une ressource d'une autre compagnie donne « n'existe pas »."""

    def get_queryset(self):
        qs = super().get_queryset()
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated or request.user.membership is None:
            return qs.none()
        return qs.filter(tenant=request.user.membership.tenant)


class TenantModelViewSet(viewsets.ModelViewSet):
    """ViewSet de base pour toute ressource appartenant à une compagnie."""

    permission_classes = [HasTenantPermission]
    required_perms = {}
    agency_field = None  # ex. "agency" ou "trip__agency" pour appliquer le périmètre d'agence

    def get_queryset(self):
        m = self.request.user.membership
        qs = super().get_queryset().filter(tenant=m.tenant)
        if self.agency_field:
            qs = scope_by_agency(qs, m, self.agency_field)
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=get_tenant(self.request))

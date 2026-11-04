"""Matrice rôles → permissions et classes de permission DRF.

La protection est appliquée côté backend : le frontend ne fait que masquer des boutons.
"""
from rest_framework.permissions import BasePermission

from .models import Role

# Permissions granulaires (verbe métier).
ALL_PERMISSIONS = {
    "company.manage", "agency.manage", "user.manage", "fleet.manage", "fleet.view",
    "trip.manage", "trip.view", "trip.reopen",
    "ticket.create", "ticket.view", "ticket.cancel", "ticket.reprint",
    "boarding.scan", "boarding.view",
    "manifest.view", "manifest.generate", "manifest.finalize",
    "report.view",
}

DEFAULT_ROLE_PERMISSIONS = {
    Role.COMPANY_ADMIN: set(ALL_PERMISSIONS),
    Role.AGENCY_MANAGER: {
        "agency.manage", "fleet.view", "trip.manage", "trip.view",
        "ticket.create", "ticket.view", "ticket.cancel", "ticket.reprint",
        "boarding.view", "manifest.view", "manifest.generate", "manifest.finalize", "report.view",
    },
    Role.TICKET_AGENT: {"fleet.view", "trip.view", "ticket.create", "ticket.view", "ticket.reprint"},
    Role.BOARDING_AGENT: {"trip.view", "boarding.scan", "boarding.view", "manifest.view"},
    Role.DRIVER: {"trip.view", "manifest.view"},
}


def permissions_for(membership):
    if membership is None:
        return set()
    base = set(DEFAULT_ROLE_PERMISSIONS.get(membership.role, set()))
    base |= set(membership.extra_permissions or []) & ALL_PERMISSIONS
    base -= set(membership.revoked_permissions or [])
    return base


def has_perm(user, perm):
    m = user.membership
    return bool(m and m.tenant.is_active and perm in permissions_for(m))


class IsPlatformAdmin(BasePermission):
    message = "Réservé au Super Admin de la plateforme."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_platform_admin)


class HasTenantPermission(BasePermission):
    """Exige un tenant actif et la permission `view.required_perms[action]` (ou `required_perm`)."""

    message = "Vous n'avez pas la permission d'effectuer cette action."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        membership = user.membership
        if membership is None:
            self.message = "Aucune compagnie active n'est associée à ce compte."
            return False
        if not membership.tenant.is_active:
            self.message = "Cette compagnie est suspendue."
            return False
        perms = getattr(view, "required_perms", None) or {}
        action = getattr(view, "action", None) or request.method.lower()
        needed = perms.get(action, perms.get("*", getattr(view, "required_perm", None)))
        if needed is None:
            return True
        return needed in permissions_for(membership)

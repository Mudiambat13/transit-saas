from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class AuditLog(models.Model):
    """Journal d'audit. tenant=NULL pour les actions de plateforme (Super Admin)."""

    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60, db_index=True)
    entity = models.CharField(max_length=60, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # jamais de secrets ni de données sensibles
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["tenant", "created_at"])]

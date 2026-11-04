from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenants.models import TenantOwnedModel


class ManifestType(models.TextChoices):
    PREVIEW = "PREVIEW", "Prévisionnel"
    FINAL = "FINAL", "Définitif"


class ManifestStatus(models.TextChoices):
    GENERATED = "GENERATED", "Généré"
    ARCHIVED = "ARCHIVED", "Archivé (figé)"
    SUPERSEDED = "SUPERSEDED", "Remplacé"


class Manifest(TenantOwnedModel):
    trip = models.ForeignKey("trips.Trip", on_delete=models.PROTECT, related_name="manifests")
    type = models.CharField(max_length=8, choices=ManifestType.choices)
    number = models.CharField(max_length=40)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=ManifestStatus.choices, default=ManifestStatus.GENERATED)
    # Instantané figé : en-tête du voyage, lignes passagers, totaux. Le PDF est rendu depuis ce JSON,
    # jamais depuis les tables vivantes, afin que le document archivé ne change pas.
    snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_manifest_number_per_tenant"),
            models.UniqueConstraint(fields=["trip", "type", "version"], name="uniq_manifest_version_per_trip"),
        ]

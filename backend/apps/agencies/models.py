from django.db import models

from apps.tenants.models import TenantOwnedModel


class Agency(TenantOwnedModel):
    name = models.CharField(max_length=120)
    city = models.CharField(max_length=80)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "agencies"
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="uniq_agency_name_per_tenant")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.city})"

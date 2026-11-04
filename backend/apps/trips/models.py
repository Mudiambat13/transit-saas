from django.conf import settings
from django.db import models

from apps.tenants.models import TenantOwnedModel


class TripStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    OPEN = "OPEN", "Ouvert à la vente"
    BOARDING = "BOARDING", "Embarquement"
    CLOSED = "CLOSED", "Clôturé"
    COMPLETED = "COMPLETED", "Terminé"
    CANCELLED = "CANCELLED", "Annulé"
    SUSPENDED = "SUSPENDED", "Suspendu"


class Trip(TenantOwnedModel):
    reference = models.CharField(max_length=30)
    agency = models.ForeignKey("agencies.Agency", on_delete=models.PROTECT, related_name="trips")
    origin = models.CharField(max_length=80)
    destination = models.CharField(max_length=80)
    departure_at = models.DateTimeField()
    arrival_estimated_at = models.DateTimeField(null=True, blank=True)
    bus = models.ForeignKey("fleet.Bus", on_delete=models.PROTECT, related_name="trips")
    drivers = models.ManyToManyField("fleet.Driver", through="TripDriver", related_name="trips")
    # Copie de la capacité du bus au moment de la création : jamais saisie librement à la vente.
    capacity = models.PositiveSmallIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=12, choices=TripStatus.choices, default=TripStatus.DRAFT, db_index=True)
    notes = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "reference"], name="uniq_trip_ref_per_tenant")]
        ordering = ["-departure_at"]
        indexes = [models.Index(fields=["tenant", "status", "departure_at"])]

    def __str__(self):
        return f"{self.reference} {self.origin}→{self.destination}"


class TripDriver(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="trip_drivers")
    driver = models.ForeignKey("fleet.Driver", on_delete=models.PROTECT)
    role = models.CharField(max_length=30, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["trip", "driver"], name="uniq_driver_per_trip")]

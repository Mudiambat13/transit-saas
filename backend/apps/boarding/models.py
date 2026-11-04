from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenants.models import TenantOwnedModel


class ScanResult(models.TextChoices):
    VALIDATED = "VALIDATED", "Embarquement validé"
    ALREADY_BOARDED = "ALREADY_BOARDED", "Déjà embarqué"
    INVALID = "INVALID", "Billet invalide"
    CANCELLED = "CANCELLED", "Billet annulé"
    WRONG_TRIP = "WRONG_TRIP", "Mauvais voyage"
    TRIP_CLOSED = "TRIP_CLOSED", "Voyage clôturé"
    NOT_ELIGIBLE = "NOT_ELIGIBLE", "Billet non admissible"


class BoardingEvent(TenantOwnedModel):
    trip = models.ForeignKey("trips.Trip", on_delete=models.PROTECT, related_name="boarding_events")
    ticket = models.ForeignKey("ticketing.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="boarding_events")
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    device = models.CharField(max_length=80, blank=True)
    result = models.CharField(max_length=20, choices=ScanResult.choices)
    idempotency_key = models.CharField(max_length=64, blank=True)
    # Après réouverture d'un voyage, les anciens embarquements restent historisés.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # Un billet ne peut avoir qu'UN embarquement validé (garantie anti-doublon en base).
            models.UniqueConstraint(fields=["ticket"], condition=Q(result="VALIDATED"), name="uniq_validated_boarding_per_ticket"),
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="uniq_boarding_idempotency_key",
            ),
        ]
        indexes = [models.Index(fields=["trip", "result"])]

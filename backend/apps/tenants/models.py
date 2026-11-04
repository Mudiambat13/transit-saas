from django.db import models
from django.utils import timezone


class TenantStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspendue"


class Plan(models.Model):
    """Offre commerciale. Une limite à 0 signifie « illimité »."""

    name = models.CharField(max_length=80, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="USD")
    period = models.CharField(max_length=10, default="MONTHLY")
    max_agencies = models.PositiveIntegerField(default=0)
    max_users = models.PositiveIntegerField(default=0)
    max_trips_per_month = models.PositiveIntegerField(default=0)
    max_tickets_per_month = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Tenant(models.Model):
    """Compagnie de transport (locataire du SaaS)."""

    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    status = models.CharField(max_length=12, choices=TenantStatus.choices, default=TenantStatus.ACTIVE)
    currency = models.CharField(max_length=3, default="USD")
    timezone = models.CharField(max_length=64, default="Africa/Lubumbashi")
    logo = models.ImageField(upload_to="logos/", null=True, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=255, blank=True)
    settings = models.JSONField(default=dict, blank=True)  # ex: {"passenger_phone_required": true, "seat_selection": true}
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.status == TenantStatus.ACTIVE

    def setting(self, key, default=None):
        return (self.settings or {}).get(key, default)

    @property
    def current_plan(self):
        sub = self.subscriptions.filter(status="ACTIVE").order_by("-starts_at").first()
        return sub.plan if sub else None


class Subscription(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=12, default="ACTIVE")
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.tenant} / {self.plan}"


class TenantOwnedModel(models.Model):
    """Base abstraite : toute entité métier appartient obligatoirement à un tenant."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q

from apps.tenants.models import Tenant


class Role(models.TextChoices):
    COMPANY_ADMIN = "COMPANY_ADMIN", "Administrateur de compagnie"
    AGENCY_MANAGER = "AGENCY_MANAGER", "Responsable d'agence"
    TICKET_AGENT = "TICKET_AGENT", "Agent de billetterie"
    BOARDING_AGENT = "BOARDING_AGENT", "Agent d'embarquement"
    DRIVER = "DRIVER", "Chauffeur / contrôleur"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("L'email est obligatoire.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_platform_admin", True)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    # Super Admin de la plateforme (éditeur du SaaS) : n'appartient à aucun tenant.
    is_platform_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

    @property
    def membership(self):
        """Adhésion active unique (MVP : un utilisateur = une compagnie)."""
        if not hasattr(self, "_membership_cache"):
            self._membership_cache = (
                self.memberships.select_related("tenant", "agency").filter(is_active=True).first()
            )
        return self._membership_cache


class Membership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    # Périmètre d'agence (responsable d'agence / agents). Null = toute la compagnie.
    agency = models.ForeignKey("agencies.Agency", null=True, blank=True, on_delete=models.SET_NULL, related_name="memberships")
    # Permissions additionnelles / retirées par compagnie (matrice configurable).
    extra_permissions = models.JSONField(default=list, blank=True)
    revoked_permissions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=Q(is_active=True), name="one_active_membership_per_user"),
            models.UniqueConstraint(fields=["user", "tenant"], name="unique_user_tenant"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.tenant} ({self.role})"

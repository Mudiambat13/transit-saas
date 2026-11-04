from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts import views as accounts
from apps.agencies.api import AgencyViewSet
from apps.boarding import api as boarding
from apps.fleet.api import BusViewSet, DriverViewSet
from apps.manifests import api as manifests
from apps.reports import api as reports
from apps.tenants import api as platform
from apps.ticketing.api import TicketViewSet
from apps.trips.api import TripViewSet

router = DefaultRouter()
router.register("agencies", AgencyViewSet, basename="agency")
router.register("users", accounts.UserViewSet, basename="user")
router.register("buses", BusViewSet, basename="bus")
router.register("drivers", DriverViewSet, basename="driver")
router.register("trips", TripViewSet, basename="trip")
router.register("tickets", TicketViewSet, basename="ticket")

platform_router = DefaultRouter()
platform_router.register("tenants", platform.PlatformTenantViewSet, basename="platform-tenant")
platform_router.register("plans", platform.PlanViewSet, basename="platform-plan")

urlpatterns = [
    path("auth/login/", accounts.LoginView.as_view()),
    path("auth/refresh/", accounts.RefreshView.as_view()),
    path("auth/logout/", accounts.LogoutView.as_view()),
    path("auth/me/", accounts.MeView.as_view()),
    path("company/profile/", accounts.CompanyProfileView.as_view()),
    path("company/audit/", accounts.AuditLogListView.as_view()),
    path("platform/metrics/", platform.PlatformMetricsView.as_view()),
    path("platform/audit/", platform.PlatformAuditView.as_view()),
    path("platform/", include(platform_router.urls)),
    path("boarding/scan/", boarding.ScanView.as_view()),
    path("trips/<int:trip_id>/boarding/", boarding.TripBoardingView.as_view()),
    path("trips/<int:trip_id>/boarding/events/", boarding.TripBoardingEventsView.as_view()),
    path("trips/<int:trip_id>/manifests/", manifests.TripManifestsView.as_view()),
    path("trips/<int:trip_id>/manifests/preview/", manifests.PreviewManifestView.as_view()),
    path("trips/<int:trip_id>/manifests/finalize/", manifests.FinalizeManifestView.as_view()),
    path("trips/<int:trip_id>/stats/", reports.TripStatsView.as_view()),
    path("manifests/<int:pk>/", manifests.ManifestDetailView.as_view()),
    path("manifests/<int:pk>/pdf/", manifests.ManifestPdfView.as_view()),
    path("reports/dashboard/", reports.DashboardView.as_view()),
    path("", include(router.urls)),
]

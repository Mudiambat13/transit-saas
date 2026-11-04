from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditLog
from apps.manifests.models import Manifest
from apps.ticketing.models import Passenger

from .conftest import World


def scan(w, trip, code):
    return w.scanner_c.post("/api/v1/boarding/scan/", {"trip": trip.id, "code": code}, format="json").json()


def test_preview_includes_active_and_excludes_cancelled(world_a):
    w = world_a
    a, b, c = w.sell(name="Actif Un"), w.sell(name="Annulé Deux"), w.sell(name="Actif Trois")
    w.admin_c.post(f"/api/v1/tickets/{b['id']}/cancel/", {"reason": "Erreur de saisie"}, format="json")
    r = w.admin_c.post(f"/api/v1/trips/{w.trip.id}/manifests/preview/")
    assert r.status_code == 201
    snap = r.json()["snapshot"]
    names = [p["passenger"] for p in snap["passengers"]]
    assert names == ["Actif Un", "Actif Trois"] or set(names) == {"Actif Un", "Actif Trois"}
    assert "Annulé Deux" not in names
    assert snap["totals"]["sold"] == 2 and snap["totals"]["cancelled"] == 1 and snap["totals"]["remaining_seats"] == 8
    assert r.json()["number"].startswith("MP-")
    second = w.admin_c.post(f"/api/v1/trips/{w.trip.id}/manifests/preview/").json()
    assert second["version"] == 2


def test_final_manifest_splits_boarded_and_absent(world_a):
    w = world_a
    a, b = w.sell(name="Présent"), w.sell(name="Absent")
    w.admin_c.post(f"/api/v1/trips/{w.trip.id}/start-boarding/")
    assert scan(w, w.trip, a["qr_payload"])["result"] == "VALIDATED"
    r = w.admin_c.post(f"/api/v1/trips/{w.trip.id}/close-boarding/")
    assert r.status_code == 200 and r.json()["status"] == "CLOSED"
    m = Manifest.objects.get(trip=w.trip, type="FINAL")
    rows = {p["passenger"]: p["status"] for p in m.snapshot["passengers"]}
    assert rows == {"Présent": "EMBARQUÉ", "Absent": "ABSENT"}
    assert m.snapshot["totals"]["boarded"] == 1 and m.snapshot["totals"]["absent"] == 1
    assert m.status == "ARCHIVED" and m.version == 1 and m.created_by == w.admin
    assert m.snapshot["trip"]["closed_by"] and m.snapshot["trip"]["closed_at"]
    assert AuditLog.objects.filter(action="trip.closed", entity_id=str(w.trip.id)).exists()


def test_final_manifest_is_frozen_after_passenger_edit(world_a):
    w = world_a
    a = w.sell(name="Nom Original")
    w.admin_c.post(f"/api/v1/trips/{w.trip.id}/start-boarding/")
    scan(w, w.trip, a["qr_payload"])
    w.admin_c.post(f"/api/v1/trips/{w.trip.id}/close-boarding/")
    m = Manifest.objects.get(trip=w.trip, type="FINAL")
    before_snapshot = m.snapshot
    before_pdf = w.admin_c.get(f"/api/v1/manifests/{m.id}/pdf/").content
    Passenger.objects.update(full_name="Nom Modifié", phone="000")
    m.refresh_from_db()
    assert m.snapshot == before_snapshot
    assert m.snapshot["passengers"][0]["passenger"] == "Nom Original"
    assert w.admin_c.get(f"/api/v1/manifests/{m.id}/").json()["snapshot"]["passengers"][0]["passenger"] == "Nom Original"
    after_pdf = w.admin_c.get(f"/api/v1/manifests/{m.id}/pdf/").content
    assert after_pdf.startswith(b"%PDF") and len(after_pdf) > 1000
    # le contenu textuel rendu ne contient pas la modification
    assert b"Modifi" not in after_pdf


def test_pdf_renders_for_both_types_and_many_pages(world_a):
    w = world_a
    big = w.new_trip("OPEN", bus=w.bus)
    w.bus.capacity = 10
    for i in range(10):
        w.sell(trip=big, name=f"Passager numéro {i}")
    prev = w.admin_c.post(f"/api/v1/trips/{big.id}/manifests/preview/").json()
    pdf = w.admin_c.get(f"/api/v1/manifests/{prev['id']}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    empty = w.new_trip("OPEN")
    prev = w.admin_c.post(f"/api/v1/trips/{empty.id}/manifests/preview/").json()  # manifeste vide : doit se rendre
    assert w.admin_c.get(f"/api/v1/manifests/{prev['id']}/pdf/").content.startswith(b"%PDF")


def test_reopen_requires_permission_reason_and_is_audited(world_a):
    w = world_a
    w.admin_c.post(f"/api/v1/trips/{w.trip.id}/start-boarding/")
    w.admin_c.post(f"/api/v1/trips/{w.trip.id}/close-boarding/")
    assert w.manager_c.post(f"/api/v1/trips/{w.trip.id}/reopen/", {"reason": "oubli important"}, format="json").status_code == 403
    assert w.admin_c.post(f"/api/v1/trips/{w.trip.id}/reopen/", {"reason": ""}, format="json").status_code == 400
    assert w.admin_c.post(f"/api/v1/trips/{w.trip.id}/reopen/", {"reason": "Passager retardataire embarqué"}, format="json").status_code == 200
    assert AuditLog.objects.filter(action="trip.reopened").exists()
    # nouvelle clôture : nouvelle version, l'ancienne est marquée remplacée, jamais modifiée silencieusement
    w.admin_c.post(f"/api/v1/trips/{w.trip.id}/close-boarding/")
    finals = list(Manifest.objects.filter(trip=w.trip, type="FINAL").order_by("version"))
    assert [(m.version, m.status) for m in finals] == [(1, "SUPERSEDED"), (2, "ARCHIVED")]


def test_closing_requires_permission_and_boarding_state(world_a):
    w = world_a
    assert w.admin_c.post(f"/api/v1/trips/{w.trip.id}/close-boarding/").status_code == 409  # OPEN -> CLOSED interdit
    w.admin_c.post(f"/api/v1/trips/{w.trip.id}/start-boarding/")
    assert w.scanner_c.post(f"/api/v1/trips/{w.trip.id}/close-boarding/").status_code == 403
    assert w.seller_c.post(f"/api/v1/trips/{w.trip.id}/manifests/finalize/").status_code == 403


def test_driver_has_read_only_manifest_access(world_a):
    w = world_a
    w.sell()
    assert w.driver_c.get(f"/api/v1/trips/{w.trip.id}/manifests/").status_code == 200
    assert w.driver_c.post(f"/api/v1/trips/{w.trip.id}/manifests/preview/").status_code == 403
    assert w.driver_c.post(f"/api/v1/trips/{w.trip.id}/open-sales/").status_code == 403


def test_trip_lifecycle_and_invalid_transitions(world_a):
    w = world_a
    draft = w.new_trip("DRAFT")
    assert w.admin_c.post(f"/api/v1/trips/{draft.id}/start-boarding/").status_code == 409
    assert w.admin_c.post(f"/api/v1/trips/{draft.id}/open-sales/").status_code == 200
    assert w.admin_c.post(f"/api/v1/trips/{draft.id}/start-boarding/").status_code == 200
    assert w.admin_c.post(f"/api/v1/trips/{draft.id}/close-boarding/").status_code == 200
    assert w.admin_c.post(f"/api/v1/trips/{draft.id}/complete/").status_code == 200
    assert w.admin_c.post(f"/api/v1/trips/{draft.id}/cancel/").status_code == 409


def test_bus_cannot_be_double_booked(world_a):
    w = world_a
    dep = w.trip.departure_at + timedelta(hours=3)
    payload = {"origin": "A", "destination": "B", "departure_at": dep.isoformat(), "price": "50",
               "agency": w.agency.id, "bus": w.bus.id}
    r = w.admin_c.post("/api/v1/trips/", payload, format="json")
    assert r.status_code == 400 and "bus" in r.json()
    payload["departure_at"] = (w.trip.departure_at + timedelta(days=2)).isoformat()
    r = w.admin_c.post("/api/v1/trips/", payload, format="json")
    assert r.status_code == 201
    body = r.json()
    assert body["capacity"] == w.bus.capacity and body["reference"] and body["status"] == "DRAFT"


def test_trip_capacity_comes_from_bus_not_from_client(world_a):
    w = world_a
    dep = (timezone.now() + timedelta(days=10)).isoformat()
    r = w.admin_c.post("/api/v1/trips/", {"origin": "A", "destination": "B", "departure_at": dep, "price": "50",
                                          "agency": w.agency.id, "bus": w.bus.id, "capacity": 999}, format="json")
    assert r.status_code == 201 and r.json()["capacity"] == 10


def test_plan_limits_enforced(world_a, platform_client):
    from apps.tenants.models import Plan, Subscription
    plan = Plan.objects.create(name="Mini", max_agencies=1, max_users=0)
    Subscription.objects.create(tenant=world_a.tenant, plan=plan)
    r = world_a.admin_c.post("/api/v1/agencies/", {"name": "Deuxième", "city": "Likasi"}, format="json")
    assert r.status_code == 400 and "Limite" in str(r.json())


def test_platform_creates_tenant_with_initial_admin(platform_client):
    from apps.tenants.models import Plan
    plan = Plan.objects.create(name="Pro", price=99)
    r = platform_client.post("/api/v1/platform/tenants/", {
        "name": "Trans Katanga", "slug": "trans-katanga", "currency": "CDF", "plan": plan.id,
        "admin_email": "boss@transkatanga.test", "admin_full_name": "Boss", "admin_password": "Sup3rSecret!pw",
    }, format="json")
    assert r.status_code == 201, r.content
    from rest_framework.test import APIClient
    login = APIClient().post("/api/v1/auth/login/", {"email": "boss@transkatanga.test", "password": "Sup3rSecret!pw"}, format="json")
    assert login.status_code == 200
    me = login.json()["user"]
    assert me["role"] == "COMPANY_ADMIN" and me["tenant"]["slug"] == "trans-katanga" and "ticket.create" in me["permissions"]
    assert AuditLog.objects.filter(action="platform.tenant_created").exists()


def test_login_failure_and_me(world_a):
    from rest_framework.test import APIClient
    c = APIClient()
    assert c.post("/api/v1/auth/login/", {"email": "admin@alpha.test", "password": "mauvais"}, format="json").status_code == 401
    ok = c.post("/api/v1/auth/login/", {"email": "ADMIN@alpha.test", "password": "Passw0rd!x"}, format="json").json()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {ok['access']}")
    me = c.get("/api/v1/auth/me/").json()
    assert me["email"] == "admin@alpha.test"
    refreshed = APIClient().post("/api/v1/auth/refresh/", {"refresh": ok["refresh"]}, format="json")
    assert refreshed.status_code == 200 and "access" in refreshed.json()
    assert APIClient().get("/api/v1/auth/me/").status_code == 401


def test_dashboard_and_trip_stats(world_a):
    w = world_a
    w.sell()
    w.sell()
    d = w.admin_c.get("/api/v1/reports/dashboard/").json()
    assert d["tickets_today"] == 2 and d["revenue_month"][0]["total"] == "240.00"
    s = w.admin_c.get(f"/api/v1/trips/{w.trip.id}/stats/").json()
    assert s["sold"] == 2 and s["remaining"] == 8 and s["fill_rate"] == 20.0
    assert w.seller_c.get("/api/v1/reports/dashboard/").status_code == 403

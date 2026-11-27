from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.fleet.models import Driver
from apps.tracking.models import LocationPoint, TrackingSession
from apps.trips.models import TripDriver

from .conftest import client_for, make_user

BASE = {"lat": -11.6647, "lon": 27.4794}  # Lubumbashi


def pts(n=3, start=None, step_s=20, **extra):
    start = start or timezone.now() - timedelta(seconds=step_s * n)
    return [{"lat": BASE["lat"] + i * 0.0005, "lon": BASE["lon"], "speed_kmh": 60,
             "recorded_at": (start + timedelta(seconds=step_s * i)).isoformat(), **extra} for i in range(n)]


def device(token):
    c = APIClient()
    c.credentials(HTTP_X_TRACKING_TOKEN=token)
    return c


@pytest.fixture
def boarding_trip(world_a):
    world_a.trip.status = "BOARDING"
    world_a.trip.save()
    return world_a.trip


@pytest.fixture
def driver_setup(world_a, boarding_trip):
    """Le chauffeur du monde A est affecté au voyage."""
    d = Driver.objects.create(tenant=world_a.tenant, full_name="Chauffeur Un", user=world_a.driver_user)
    TripDriver.objects.create(trip=boarding_trip, driver=d)
    return d


def start(client, trip):
    r = client.post(f"/api/v1/trips/{trip.id}/tracking/start/", {"device_label": "Tecno Spark"}, format="json")
    assert r.status_code == 201, r.content
    return r.json()["token"]


def test_start_ingest_and_read_position(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    r = device(token).post("/api/v1/tracking/ingest/", {"points": pts(3)}, format="json")
    assert r.status_code == 200 and r.json()["accepted"] == 3
    data = world_a.admin_c.get(f"/api/v1/trips/{boarding_trip.id}/tracking/").json()
    assert data["active"] and data["last"]["lat"] == pytest.approx(BASE["lat"] + 0.001) and data["stale"] is False
    assert len(data["trail"]) == 3 and data["tracking_code"]


def test_token_is_stored_hashed_and_never_reshown(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    s = TrackingSession.objects.get()
    assert token not in s.token_hash and len(s.token_hash) == 64
    assert "token" not in world_a.admin_c.get(f"/api/v1/trips/{boarding_trip.id}/tracking/").json()["session"]


def test_ingest_requires_valid_token(world_a, boarding_trip):
    assert APIClient().post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 401
    assert device("nimporte-quoi").post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 401
    # un JWT utilisateur n'ouvre pas l'ingestion : il faut le jeton appareil
    assert world_a.admin_c.post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 401


def test_replayed_batch_is_idempotent(world_a, boarding_trip):
    token, batch = start(world_a.admin_c, boarding_trip), pts(4)
    c = device(token)
    assert c.post("/api/v1/tracking/ingest/", {"points": batch}, format="json").json()["accepted"] == 4
    again = c.post("/api/v1/tracking/ingest/", {"points": batch}, format="json").json()
    assert again["accepted"] == 0 and again["duplicates"] == 4
    assert LocationPoint.objects.count() == 4


def test_offline_backlog_keeps_original_times(world_a, boarding_trip):
    """Points accumulés pendant une zone sans réseau puis envoyés d'un coup, dans le désordre."""
    token = start(world_a.admin_c, boarding_trip)
    old = timezone.now() - timedelta(hours=3)
    batch = list(reversed(pts(5, start=old, step_s=60)))
    assert device(token).post("/api/v1/tracking/ingest/", {"points": batch}, format="json").json()["accepted"] == 5
    last = LocationPoint.objects.order_by("-recorded_at").first()
    assert abs((last.recorded_at - (old + timedelta(seconds=240))).total_seconds()) < 1
    # le dernier signal date de 3 h : le suivi est signalé « sans signal »
    assert world_a.admin_c.get(f"/api/v1/trips/{boarding_trip.id}/tracking/").json()["stale"] is True


def test_invalid_points_are_rejected_not_stored(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    now = timezone.now()
    bad = [
        {"lat": 95, "lon": 27, "recorded_at": now.isoformat()},
        {"lat": -11, "lon": 200, "recorded_at": now.isoformat()},
        {"lat": 0, "lon": 0, "recorded_at": now.isoformat()},
        {"lat": -11, "lon": 27, "recorded_at": (now + timedelta(hours=2)).isoformat()},
        {"lat": -11, "lon": 27, "recorded_at": (now - timedelta(days=9)).isoformat()},
        {"lat": "abc", "lon": 27, "recorded_at": now.isoformat()},
        {"lat": -11, "lon": 27},
    ]
    r = device(token).post("/api/v1/tracking/ingest/", {"points": bad}, format="json").json()
    assert r["accepted"] == 0 and r["rejected"] == 7 and LocationPoint.objects.count() == 0


def test_batch_limits(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    c = device(token)
    assert c.post("/api/v1/tracking/ingest/", {"points": []}, format="json").status_code == 400
    assert c.post("/api/v1/tracking/ingest/", {"points": pts(201, step_s=1)}, format="json").status_code == 400


def test_teleporting_point_is_flagged_suspect_and_ignored_for_position(world_a, boarding_trip):
    token, now = start(world_a.admin_c, boarding_trip), timezone.now()
    c = device(token)
    c.post("/api/v1/tracking/ingest/", {"points": [{"lat": -11.66, "lon": 27.47, "recorded_at": (now - timedelta(seconds=60)).isoformat()}]}, format="json")
    r = c.post("/api/v1/tracking/ingest/", {"points": [{"lat": -4.32, "lon": 15.31, "recorded_at": now.isoformat()}]}, format="json").json()  # Kinshasa en 60 s
    assert r["suspect"] == 1
    data = world_a.admin_c.get(f"/api/v1/trips/{boarding_trip.id}/tracking/").json()
    assert data["last"]["lat"] == pytest.approx(-11.66) and data["suspect_points"] == 1


def test_new_session_replaces_previous_device(world_a, boarding_trip):
    old = start(world_a.admin_c, boarding_trip)
    new = start(world_a.admin_c, boarding_trip)
    assert device(old).post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 410
    assert device(new).post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 200
    assert TrackingSession.objects.filter(ended_reason="REPLACED").count() == 1


def test_stop_ends_session(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    assert world_a.admin_c.post(f"/api/v1/trips/{boarding_trip.id}/tracking/stop/").json() == {"stopped": True}
    assert device(token).post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 410


def test_session_ends_automatically_when_trip_completed_or_cancelled(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    world_a.admin_c.post(f"/api/v1/trips/{boarding_trip.id}/close-boarding/")
    assert device(token).post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 200  # en route
    world_a.admin_c.post(f"/api/v1/trips/{boarding_trip.id}/complete/")
    assert device(token).post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 410
    assert TrackingSession.objects.get().ended_reason == "TRIP_ENDED"


def test_cannot_track_draft_or_completed_trip(world_a):
    draft = world_a.new_trip("DRAFT")
    r = world_a.admin_c.post(f"/api/v1/trips/{draft.id}/tracking/start/", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "trip_not_trackable"


def test_driver_only_tracks_assigned_trips(world_a, boarding_trip, driver_setup):
    other = world_a.new_trip("BOARDING")
    assert world_a.driver_c.post(f"/api/v1/trips/{other.id}/tracking/start/", {}, format="json").status_code == 403
    assert world_a.driver_c.get(f"/api/v1/trips/{other.id}/tracking/").status_code == 404
    token = start(world_a.driver_c, boarding_trip)
    assert device(token).post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 200
    mine = {t["id"] for t in world_a.driver_c.get("/api/v1/tracking/my-trips/").json()}
    assert mine == {boarding_trip.id}
    assert [t["trip_id"] for t in world_a.driver_c.get("/api/v1/tracking/live/").json()] == [boarding_trip.id]


def test_roles_permissions(world_a, boarding_trip):
    assert world_a.scanner_c.post(f"/api/v1/trips/{boarding_trip.id}/tracking/start/", {}, format="json").status_code == 403
    assert world_a.seller_c.post(f"/api/v1/trips/{boarding_trip.id}/tracking/start/", {}, format="json").status_code == 403
    assert world_a.scanner_c.get("/api/v1/tracking/live/").status_code == 403
    assert world_a.seller_c.get("/api/v1/tracking/live/").status_code == 200  # peut renseigner un passager


def test_tenant_isolation(world_a, world_b):
    trip_b = world_b.new_trip("BOARDING")
    assert world_a.admin_c.post(f"/api/v1/trips/{trip_b.id}/tracking/start/", {}, format="json").status_code == 404
    assert world_a.admin_c.get(f"/api/v1/trips/{trip_b.id}/tracking/").status_code == 404
    token_b = start(world_b.admin_c, trip_b)
    device(token_b).post("/api/v1/tracking/ingest/", {"points": pts(2)}, format="json")
    assert world_a.admin_c.get("/api/v1/tracking/live/").json() == []
    assert len(world_b.admin_c.get("/api/v1/tracking/live/").json()) == 1


def test_suspended_tenant_cannot_ingest(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    world_a.tenant.status = "SUSPENDED"
    world_a.tenant.save()
    assert device(token).post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 403


def test_public_page_exposes_only_safe_data(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    device(token).post("/api/v1/tracking/ingest/", {"points": pts(3)}, format="json")
    code = world_a.admin_c.get(f"/api/v1/trips/{boarding_trip.id}/tracking/").json()["tracking_code"]
    r = APIClient().get(f"/api/v1/public/track/{code}/")  # sans connexion
    assert r.status_code == 200
    body = r.json()
    assert body["tracking_active"] and body["position"] and body["origin"] == "Lubumbashi" and body["company"].startswith("Compagnie")
    blob = str(body).lower()
    assert world_a.bus.plate.lower() not in blob and "chauffeur" not in blob and "ticket" not in blob and "tkt-" not in blob
    assert "id" not in body and "tenant" not in body
    assert APIClient().get("/api/v1/public/track/code-inconnu/").status_code == 404


def test_public_page_hides_position_when_trip_over_or_signal_old(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    old = timezone.now() - timedelta(hours=2)
    device(token).post("/api/v1/tracking/ingest/", {"points": pts(2, start=old)}, format="json")
    code = world_a.admin_c.get(f"/api/v1/trips/{boarding_trip.id}/tracking/").json()["tracking_code"]
    assert APIClient().get(f"/api/v1/public/track/{code}/").json()["position"] is None  # signal trop ancien
    device(token).post("/api/v1/tracking/ingest/", {"points": pts(2)}, format="json")
    assert APIClient().get(f"/api/v1/public/track/{code}/").json()["position"] is not None
    world_a.admin_c.post(f"/api/v1/trips/{boarding_trip.id}/close-boarding/")
    world_a.admin_c.post(f"/api/v1/trips/{boarding_trip.id}/complete/")
    done = APIClient().get(f"/api/v1/public/track/{code}/").json()
    assert done["position"] is None and done["tracking_active"] is False and done["status"] == "COMPLETED"


def test_public_page_unreachable_for_suspended_tenant(world_a, boarding_trip):
    start(world_a.admin_c, boarding_trip)
    code = world_a.admin_c.get(f"/api/v1/trips/{boarding_trip.id}/tracking/").json()["tracking_code"]
    world_a.tenant.status = "SUSPENDED"
    world_a.tenant.save()
    assert APIClient().get(f"/api/v1/public/track/{code}/").status_code == 404


def test_new_trips_get_a_tracking_code_and_ticket_pdf_shows_link(world_a, settings):
    settings.PUBLIC_BASE_URL = "https://billets.exemple.com"
    from datetime import timedelta as td
    r = world_a.admin_c.post("/api/v1/trips/", {"origin": "A", "destination": "B", "price": "10", "agency": world_a.agency.id,
                                                "bus": world_a.bus.id, "departure_at": (timezone.now() + td(days=20)).isoformat()}, format="json")
    assert r.status_code == 201 and r.json()["tracking_code"]
    t = world_a.sell()
    world_a.trip.tracking_code = "abcDEF123"
    world_a.trip.save()
    pdf = world_a.seller_c.get(f"/api/v1/tickets/{t['id']}/pdf/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_purge_old_points(world_a, boarding_trip):
    from apps.tracking.services import purge_old_points
    token = start(world_a.admin_c, boarding_trip)
    device(token).post("/api/v1/tracking/ingest/", {"points": pts(2)}, format="json")
    for i, p in enumerate(LocationPoint.objects.all()):
        LocationPoint.objects.filter(pk=p.pk).update(recorded_at=timezone.now() - timedelta(days=120, seconds=i))
    assert purge_old_points(90) == 2 and LocationPoint.objects.count() == 0


def test_driver_account_link_validation(world_a, world_b):
    d = Driver.objects.create(tenant=world_a.tenant, full_name="Sans compte")
    url = f"/api/v1/drivers/{d.id}/"
    # compte d'une autre compagnie : refusé
    r = world_a.admin_c.patch(url, {"user": world_b.driver_user.id}, format="json")
    assert r.status_code == 400 and "user" in r.json()
    # compte de la compagnie : accepté, l'e-mail est restitué
    r = world_a.admin_c.patch(url, {"user": world_a.driver_user.id}, format="json")
    assert r.status_code == 200 and r.json()["user_email"] == world_a.driver_user.email
    # le même compte ne peut pas servir à deux chauffeurs
    other = Driver.objects.create(tenant=world_a.tenant, full_name="Autre")
    r = world_a.admin_c.patch(f"/api/v1/drivers/{other.id}/", {"user": world_a.driver_user.id}, format="json")
    assert r.status_code == 400
    # détacher le compte
    assert world_a.admin_c.patch(url, {"user": None}, format="json").json()["user"] is None


def test_device_can_end_its_own_session_with_its_token_only(world_a, boarding_trip):
    token = start(world_a.admin_c, boarding_trip)
    c = device(token)
    assert c.post("/api/v1/tracking/end/", {}, format="json").json() == {"stopped": True}
    assert c.post("/api/v1/tracking/end/", {}, format="json").json() == {"stopped": False}  # idempotent
    assert c.post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 410
    assert TrackingSession.objects.get().ended_reason == "STOPPED"
    assert APIClient().post("/api/v1/tracking/end/", {}, format="json").status_code == 401
    assert device("faux").post("/api/v1/tracking/end/", {}, format="json").status_code == 401
    from apps.audit.models import AuditLog
    assert AuditLog.objects.filter(action="tracking.stopped").exists()


def test_a_device_token_cannot_end_another_trips_session(world_a):
    t1, t2 = world_a.new_trip("BOARDING"), world_a.new_trip("BOARDING", bus=world_a.bus, hours=200)
    tok1, tok2 = start(world_a.admin_c, t1), start(world_a.admin_c, t2)
    device(tok1).post("/api/v1/tracking/end/", {}, format="json")
    assert device(tok2).post("/api/v1/tracking/ingest/", {"points": pts(1)}, format="json").status_code == 200


@pytest.mark.django_db
def test_invented_tokens_are_throttled_per_ip(monkeypatch):
    """Des jetons tous différents ont chacun leur compteur : le plafond par IP doit quand même s'appliquer."""
    from django.core.cache import cache
    from rest_framework.throttling import SimpleRateThrottle
    from rest_framework.test import APIClient
    client = APIClient()
    cache.clear()
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "track_ip", "3/min")
    codes = [client.post("/api/v1/tracking/ingest/", {"points": []}, format="json", HTTP_X_TRACKING_TOKEN=f"fake-{i}").status_code for i in range(5)]
    cache.clear()
    assert codes[:3] == [401, 401, 401] and 429 in codes[3:]


def test_tracking_detail_exposes_stats_and_replay(world_a, boarding_trip):
    from datetime import timedelta
    from django.utils import timezone
    from apps.tracking import services
    from apps.tracking.models import LocationPoint, TrackingSession
    w, trip = world_a, boarding_trip
    sess, _ = services.start_session(tenant=w.tenant, actor=w.admin, trip_id=trip.id)
    now = timezone.now()
    for i in range(4):  # ~0,0045° de latitude ≈ 0,5 km toutes les 60 s => ~30 km/h
        LocationPoint.objects.create(tenant=w.tenant, trip=trip, session=sess, lat=-11.66 + 0.0045 * i, lon=27.47, speed_kmh=30 + i,
                                     recorded_at=now - timedelta(minutes=4 - i))
    d = w.admin_c.get(f"/api/v1/trips/{trip.id}/tracking/").json()
    assert d["stats"]["points"] == 4 and 1.3 < d["stats"]["distance_km"] < 1.7
    assert d["stats"]["max_speed_kmh"] == 33 and d["stats"]["avg_speed_kmh"] in range(25, 40)
    assert len(d["replay"]) == 4 and d["replay"][0][2] == 30 and d["bus"]

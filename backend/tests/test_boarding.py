import threading

import pytest
from django.db import IntegrityError, connection, transaction

from apps.boarding.models import BoardingEvent
from apps.boarding import services as boarding_services
from apps.ticketing.models import Ticket


def scan(client, trip, code, **extra):
    r = client.post("/api/v1/boarding/scan/", {"trip": trip.id, "code": code, **extra}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


@pytest.fixture
def boarding_world(world_a):
    t = world_a.sell(name="Alice Test")
    trip = world_a.trip
    trip.status = "BOARDING"
    trip.save()
    return world_a, trip, t


def test_valid_ticket_is_accepted_once(boarding_world):
    w, trip, t = boarding_world
    out = scan(w.scanner_c, trip, t["qr_payload"])
    assert out["result"] == "VALIDATED" and out["color"] == "green"
    assert out["ticket"]["passenger"] == "Alice Test"
    again = scan(w.scanner_c, trip, t["qr_payload"])
    assert again["result"] == "ALREADY_BOARDED" and again["color"] == "red"
    assert BoardingEvent.objects.filter(ticket_id=t["id"], result="VALIDATED").count() == 1


def test_manual_reference_fallback(boarding_world):
    w, trip, t = boarding_world
    assert scan(w.scanner_c, trip, t["reference"].lower())["result"] == "VALIDATED"


def test_ticket_of_other_trip_is_refused(boarding_world):
    w, trip, t = boarding_world
    other = w.new_trip("BOARDING")
    other_t = w.sell(trip=other, name="Autre Voyage")
    out = scan(w.scanner_c, trip, other_t["qr_payload"])
    assert out["result"] == "WRONG_TRIP" and out["color"] == "orange"
    assert not BoardingEvent.objects.filter(ticket_id=other_t["id"], result="VALIDATED").exists()


def test_unknown_and_tampered_qr_refused(boarding_world):
    w, trip, t = boarding_world
    assert scan(w.scanner_c, trip, "inconnu.abcdef123456")["result"] == "INVALID"
    assert scan(w.scanner_c, trip, "n'importe quoi")["result"] == "INVALID"
    token, sig = t["qr_payload"].rsplit(".", 1)
    assert scan(w.scanner_c, trip, f"{token}x.{sig}")["result"] == "INVALID"
    assert scan(w.scanner_c, trip, f"{token}.{'0' * 12}")["result"] == "INVALID"
    assert not BoardingEvent.objects.filter(result="VALIDATED").exists()


def test_cancelled_ticket_refused(boarding_world):
    w, trip, t = boarding_world
    w.admin_c.post(f"/api/v1/tickets/{t['id']}/cancel/", {"reason": "Remboursé"}, format="json")
    out = scan(w.scanner_c, trip, t["qr_payload"])
    assert out["result"] == "CANCELLED" and out["color"] == "orange"


def test_scan_before_boarding_started_and_after_close(world_a):
    t = world_a.sell()
    assert scan(world_a.scanner_c, world_a.trip, t["qr_payload"])["result"] == "NOT_ELIGIBLE"
    world_a.trip.status = "CLOSED"
    world_a.trip.save()
    assert scan(world_a.scanner_c, world_a.trip, t["qr_payload"])["result"] == "TRIP_CLOSED"


def test_scan_after_closing_through_api_is_refused(boarding_world):
    w, trip, t = boarding_world
    assert w.admin_c.post(f"/api/v1/trips/{trip.id}/close-boarding/").status_code == 200
    assert scan(w.scanner_c, trip, t["qr_payload"])["result"] == "TRIP_CLOSED"


def test_every_attempt_is_audited_including_refusals(boarding_world):
    from apps.audit.models import AuditLog
    w, trip, t = boarding_world
    scan(w.scanner_c, trip, t["qr_payload"])
    scan(w.scanner_c, trip, t["qr_payload"])
    scan(w.scanner_c, trip, "bidon.000000000000")
    actions = set(AuditLog.objects.filter(action__startswith="boarding.").values_list("action", flat=True))
    assert {"boarding.validated", "boarding.already_boarded", "boarding.invalid"} <= actions
    # pas de données sensibles dans l'audit : ni jeton QR ni nom du passager
    dump = str(list(AuditLog.objects.values_list("metadata", flat=True)))
    assert t["qr_payload"].split(".")[0] not in dump and "Alice" not in dump


def test_idempotency_key_replay_does_not_double_count(boarding_world):
    w, trip, t = boarding_world
    a = scan(w.scanner_c, trip, t["qr_payload"], idempotency_key="req-123")
    b = scan(w.scanner_c, trip, t["qr_payload"], idempotency_key="req-123")
    assert a["result"] == b["result"] == "VALIDATED" and b["replay"] is True
    assert BoardingEvent.objects.filter(ticket_id=t["id"]).count() == 1


def test_only_boarding_role_can_scan(boarding_world):
    w, trip, t = boarding_world
    body = {"trip": trip.id, "code": t["qr_payload"]}
    assert w.seller_c.post("/api/v1/boarding/scan/", body, format="json").status_code == 403
    assert w.driver_c.post("/api/v1/boarding/scan/", body, format="json").status_code == 403
    assert w.admin_c.post("/api/v1/boarding/scan/", body, format="json").status_code == 200


def test_boarding_agent_cannot_alter_commercial_data(boarding_world):
    w, trip, t = boarding_world
    assert w.scanner_c.post(f"/api/v1/tickets/{t['id']}/cancel/", {"reason": "triche"}, format="json").status_code == 403
    assert w.scanner_c.get("/api/v1/tickets/").status_code == 403
    assert w.scanner_c.post("/api/v1/tickets/", {"trip": trip.id, "full_name": "X Y"}, format="json").status_code == 403


def test_db_constraint_allows_only_one_validated_boarding(boarding_world):
    w, trip, t = boarding_world
    ticket = Ticket.objects.get(pk=t["id"])
    BoardingEvent.objects.create(tenant=w.tenant, trip=trip, ticket=ticket, result="VALIDATED")
    with pytest.raises(IntegrityError), transaction.atomic():
        BoardingEvent.objects.create(tenant=w.tenant, trip=trip, ticket=ticket, result="VALIDATED")
    # un refus (déjà embarqué) reste enregistrable
    BoardingEvent.objects.create(tenant=w.tenant, trip=trip, ticket=ticket, result="ALREADY_BOARDED")


@pytest.mark.django_db(transaction=True)
def test_concurrent_scans_produce_single_boarding(world_a):
    t = world_a.sell(name="Course Critique")
    trip = world_a.trip
    trip.status = "BOARDING"
    trip.save()
    results, errors = [], []
    barrier = threading.Barrier(6)

    def worker(i):
        try:
            barrier.wait()
            out = boarding_services.scan(tenant=world_a.tenant, agent=world_a.scanner, trip_id=trip.id,
                                         code=t["qr_payload"], device=f"tel-{i}")
            results.append(out["result"])
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert not errors, errors
    assert len(results) == 6, "tous les scans concurrents doivent aboutir"
    assert results.count("VALIDATED") == 1
    assert set(results) <= {"VALIDATED", "ALREADY_BOARDED"}
    assert BoardingEvent.objects.filter(ticket_id=t["id"], result="VALIDATED").count() == 1


def test_live_boarding_list(boarding_world):
    w, trip, t = boarding_world
    w.sell(name="Deuxième")
    scan(w.scanner_c, trip, t["qr_payload"])
    data = w.scanner_c.get(f"/api/v1/trips/{trip.id}/boarding/").json()
    assert data["totals"] == {"valid": 2, "boarded": 1, "remaining": 1}
    events = w.scanner_c.get(f"/api/v1/trips/{trip.id}/boarding/events/").json()
    assert events and events[0]["result"] == "VALIDATED"

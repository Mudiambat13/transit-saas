"""Construction des manifestes à partir d'un instantané figé."""
from django.db import transaction
from django.utils import timezone

from apps.audit import service as audit
from apps.boarding.models import BoardingEvent, ScanResult
from apps.ticketing.models import TicketStatus

from .models import Manifest, ManifestStatus, ManifestType


def _local_iso(dt, tzname):
    try:
        import zoneinfo
        return dt.astimezone(zoneinfo.ZoneInfo(tzname)).isoformat()
    except Exception:
        return dt.isoformat()


def build_snapshot(trip, mtype, actor):
    """Copie figée (JSON) des données du manifeste : indépendante des tables vivantes ensuite."""
    tenant = trip.tenant
    tickets = list(trip.tickets.select_related("passenger", "seat").order_by("seat__id", "id"))
    boarded = {e.ticket_id: e.created_at for e in
               BoardingEvent.objects.filter(trip=trip, result=ScanResult.VALIDATED)}
    rows, cancelled = [], 0
    for t in tickets:
        if t.status == TicketStatus.CANCELLED:
            cancelled += 1
            continue
        row = {
            "reference": t.reference, "passenger": t.passenger.full_name, "phone": t.passenger.phone,
            "id_document": f"{t.passenger.id_type} {t.passenger.id_number}".strip(),
            "seat": t.seat.code if t.seat else "", "price": str(t.price), "currency": t.currency,
        }
        if mtype == ManifestType.FINAL:
            if t.id in boarded:
                row["status"], row["boarded_at"] = "EMBARQUÉ", _local_iso(boarded[t.id], tenant.timezone)
            else:
                row["status"], row["boarded_at"] = "ABSENT", None
        else:
            row["status"], row["boarded_at"] = "VALIDE", None
        rows.append(row)

    n_boarded = sum(1 for r in rows if r["status"] == "EMBARQUÉ")
    totals = {
        "sold": len(rows), "cancelled": cancelled, "capacity": trip.capacity,
        "remaining_seats": max(trip.capacity - len(rows), 0),
    }
    if mtype == ManifestType.FINAL:
        totals.update({"boarded": n_boarded, "absent": len(rows) - n_boarded,
                       "boarding_rate": round(100 * n_boarded / len(rows), 1) if rows else 0.0})
    return {
        "type": mtype,
        "generated_at": _local_iso(timezone.now(), tenant.timezone),
        "generated_by": actor.full_name or actor.email,
        "company": {"name": tenant.name, "timezone": tenant.timezone, "phone": tenant.contact_phone,
                    "logo": tenant.logo.name if tenant.logo else ""},
        "trip": {
            "reference": trip.reference, "origin": trip.origin, "destination": trip.destination,
            "departure_at": _local_iso(trip.departure_at, tenant.timezone), "bus": trip.bus.plate,
            "agency": trip.agency.name, "price": str(trip.price), "currency": trip.currency,
            "drivers": [d.full_name for d in trip.drivers.all()],
            "closed_at": _local_iso(trip.closed_at, tenant.timezone) if trip.closed_at else None,
            "closed_by": (trip.closed_by.full_name or trip.closed_by.email) if trip.closed_by else None,
        },
        "passengers": rows,
        "totals": totals,
    }


def _next_version(trip, mtype):
    last = Manifest.objects.filter(trip=trip, type=mtype).order_by("-version").first()
    return (last.version + 1) if last else 1


@transaction.atomic
def generate_preview(trip, actor):
    version = _next_version(trip, ManifestType.PREVIEW)
    m = Manifest.objects.create(
        tenant=trip.tenant, trip=trip, type=ManifestType.PREVIEW, version=version,
        number=f"MP-{trip.reference}-V{version}", snapshot=build_snapshot(trip, ManifestType.PREVIEW, actor),
        created_by=actor, status=ManifestStatus.GENERATED,
    )
    audit.log("manifest.preview_generated", actor=actor, tenant=trip.tenant, entity="Manifest", entity_id=m.id, number=m.number)
    return m


@transaction.atomic
def finalize_manifest(trip, actor):
    """Génère et archive le manifeste définitif ; l'éventuelle version précédente est marquée remplacée."""
    Manifest.objects.filter(trip=trip, type=ManifestType.FINAL, status=ManifestStatus.ARCHIVED).update(status=ManifestStatus.SUPERSEDED)
    version = _next_version(trip, ManifestType.FINAL)
    m = Manifest.objects.create(
        tenant=trip.tenant, trip=trip, type=ManifestType.FINAL, version=version,
        number=f"MD-{trip.reference}-V{version}", snapshot=build_snapshot(trip, ManifestType.FINAL, actor),
        created_by=actor, status=ManifestStatus.ARCHIVED,
    )
    audit.log("manifest.final_archived", actor=actor, tenant=trip.tenant, entity="Manifest", entity_id=m.id,
              number=m.number, version=version)
    return m

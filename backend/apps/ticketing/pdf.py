"""Ticket PDF imprimable (reportlab : aucune dépendance système)."""
import io

from django.utils import timezone as djtz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from . import qr

BLUE = colors.HexColor("#1d4ed8")


def local_dt(dt, tzname):
    try:
        import zoneinfo
        return dt.astimezone(zoneinfo.ZoneInfo(tzname))
    except Exception:
        return dt


def render_ticket_pdf(ticket):
    tenant, trip, pax = ticket.tenant, ticket.trip, ticket.passenger
    buf = io.BytesIO()
    w, h = A5
    c = canvas.Canvas(buf, pagesize=A5)
    c.setTitle(f"Billet {ticket.reference}")

    c.setFillColor(BLUE)
    c.rect(0, h - 28 * mm, w, 28 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(12 * mm, h - 14 * mm, tenant.name[:40])
    c.setFont("Helvetica", 10)
    c.drawString(12 * mm, h - 21 * mm, "BILLET DE VOYAGE")
    if tenant.logo:
        try:
            c.drawImage(ImageReader(tenant.logo.path), w - 30 * mm, h - 25 * mm, 20 * mm, 20 * mm, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    dep = local_dt(trip.departure_at, tenant.timezone)
    y = h - 42 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(12 * mm, y, f"{trip.origin}  →  {trip.destination}"[:44])
    rows = [
        ("Départ", dep.strftime("%d/%m/%Y à %H:%M")),
        ("Voyage", trip.reference),
        ("Agence", trip.agency.name),
        ("Passager", pax.full_name),
        ("Téléphone", pax.phone or "—"),
        ("Siège", ticket.seat.code if ticket.seat else "Non attribué"),
        ("Bus", trip.bus.plate),
        ("Prix", f"{ticket.price:.2f} {ticket.currency}"),
    ]
    y -= 12 * mm
    for label, value in rows:
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#64748b"))
        c.drawString(12 * mm, y, label.upper())
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(colors.black)
        c.drawString(40 * mm, y, str(value)[:40])
        y -= 7.5 * mm

    png = qr.qr_png_bytes(qr.build_payload(ticket.public_token))
    c.drawImage(ImageReader(io.BytesIO(png)), w - 62 * mm, 24 * mm, 50 * mm, 50 * mm)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(w - 37 * mm, 18 * mm, ticket.reference)

    c.setStrokeColor(colors.HexColor("#cbd5e1"))
    c.setDash(2, 2)
    c.line(10 * mm, 14 * mm, w - 10 * mm, 14 * mm)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#64748b"))
    c.drawString(12 * mm, 9 * mm, "Présentez ce QR Code à l'embarquement. Billet strictement personnel, non remboursable après embarquement.")
    c.drawString(12 * mm, 5.5 * mm, f"Émis le {local_dt(djtz.now(), tenant.timezone):%d/%m/%Y %H:%M}")
    if ticket.status == "CANCELLED":
        c.saveState()
        c.setFillColor(colors.Color(0.8, 0, 0, alpha=0.25))
        c.setFont("Helvetica-Bold", 60)
        c.translate(w / 2, h / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, "ANNULÉ")
        c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()

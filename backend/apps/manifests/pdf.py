"""PDF du manifeste, rendu EXCLUSIVEMENT depuis l'instantané JSON archivé."""
import io
from datetime import datetime

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BLUE = colors.HexColor("#1d4ed8")
GREY = colors.HexColor("#64748b")


def _fmt(iso, with_time=True):
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")
    except Exception:
        return str(iso)


class _NumberedCanvas(canvas.Canvas):
    """Pagination « Page x / y » + pied de page avec le numéro du document."""

    footer_text = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(GREY)
            w, _ = self._pagesize
            self.drawString(12 * mm, 8 * mm, self.footer_text)
            self.drawRightString(w - 12 * mm, 8 * mm, f"Page {self._pageNumber} / {total}")
            super().showPage()
        super().save()


def render_manifest_pdf(manifest):
    snap = manifest.snapshot
    trip, company, totals = snap["trip"], snap["company"], snap["totals"]
    is_final = manifest.type == "FINAL"
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=16 * mm,
        title=f"Manifeste {manifest.number}", author=company["name"],
    )
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=17, textColor=BLUE, alignment=0, spaceAfter=2)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=9, textColor=GREY)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9)

    story = []
    head = [[Paragraph(f"<b>{company['name']}</b>", ParagraphStyle("c", fontSize=13)),
             Paragraph(f"MANIFESTE {'DÉFINITIF' if is_final else 'PRÉVISIONNEL'}<br/>"
                       f"<font size=9 color='#64748b'>N° {manifest.number} · version {manifest.version}</font>", h1)]]
    logo_path = (settings.MEDIA_ROOT / company["logo"]) if company.get("logo") else None
    if logo_path and logo_path.exists():
        head[0].insert(0, Image(str(logo_path), width=18 * mm, height=18 * mm, kind="proportional"))
    t = Table(head, colWidths=[22 * mm, 100 * mm, 140 * mm] if len(head[0]) == 3 else [110 * mm, 152 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [t, Spacer(1, 4 * mm)]

    info = [
        ["Voyage", trip["reference"], "Itinéraire", f"{trip['origin']} → {trip['destination']}"],
        ["Départ", _fmt(trip["departure_at"]), "Bus", trip["bus"]],
        ["Agence", trip["agency"], "Chauffeur(s)", ", ".join(trip["drivers"]) or "—"],
        ["Généré le", _fmt(snap["generated_at"]), "Généré par", snap["generated_by"]],
    ]
    if is_final:
        info.append(["Clôturé le", _fmt(trip.get("closed_at")), "Clôturé par", trip.get("closed_by") or "—"])
    it = Table(info, colWidths=[25 * mm, 80 * mm, 28 * mm, 129 * mm])
    it.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (0, -1), GREY), ("TEXTCOLOR", (2, 0), (2, -1), GREY),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"), ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story += [it, Spacer(1, 5 * mm)]

    header = ["N°", "Référence", "Passager", "Téléphone", "Pièce d'identité", "Siège"]
    header += ["Statut", "Embarqué à"] if is_final else ["Statut"]
    data = [header]
    for i, p in enumerate(snap["passengers"], 1):
        row = [i, p["reference"], p["passenger"], p["phone"] or "—", p["id_document"] or "—", p["seat"] or "—", p["status"]]
        if is_final:
            row.append(_fmt(p.get("boarded_at")) if p.get("boarded_at") else "—")
        data.append(row)
    if len(data) == 1:
        data.append(["", "Aucun passager", "", "", "", "", ""] + ([""] if is_final else []))
    widths = [10, 30, 62, 32, 42, 14, 24] + ([36] if is_final else [])
    scale = 262 / sum(widths)
    pt = Table(data, colWidths=[w * scale * mm for w in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    status_col = 6
    for r, p in enumerate(snap["passengers"], 1):
        if p["status"] == "ABSENT":
            style.append(("TEXTCOLOR", (status_col, r), (status_col, r), colors.HexColor("#b91c1c")))
        elif p["status"] == "EMBARQUÉ":
            style.append(("TEXTCOLOR", (status_col, r), (status_col, r), colors.HexColor("#15803d")))
    pt.setStyle(TableStyle(style))
    story += [pt, Spacer(1, 5 * mm)]

    if is_final:
        summary = (f"<b>Billets valides :</b> {totals['sold']} &nbsp;|&nbsp; <b>Embarqués :</b> {totals['boarded']} &nbsp;|&nbsp; "
                   f"<b>Absents :</b> {totals['absent']} &nbsp;|&nbsp; <b>Annulés :</b> {totals['cancelled']} &nbsp;|&nbsp; "
                   f"<b>Taux d'embarquement :</b> {totals['boarding_rate']} %")
        story.append(Paragraph("Document figé et archivé — toute correction ultérieure suit une procédure exceptionnelle tracée.", small))
    else:
        summary = (f"<b>Billets valides :</b> {totals['sold']} &nbsp;|&nbsp; <b>Annulés :</b> {totals['cancelled']} &nbsp;|&nbsp; "
                   f"<b>Capacité :</b> {totals['capacity']} &nbsp;|&nbsp; <b>Places restantes :</b> {totals['remaining_seats']}")
        story.append(Paragraph("Document prévisionnel : il reflète les ventes et annulations au moment de sa génération.", small))
    story += [Spacer(1, 2 * mm), Paragraph(summary, body)]

    class Canvas(_NumberedCanvas):
        footer_text = f"{company['name']} — {manifest.number} — généré le {_fmt(snap['generated_at'])}"

    doc.build(story, canvasmaker=Canvas)
    return buf.getvalue()

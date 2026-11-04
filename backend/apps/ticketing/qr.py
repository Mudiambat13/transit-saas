"""Jeton QR : identifiant opaque aléatoire + signature HMAC courte.

Le QR ne contient AUCUNE donnée personnelle ni identifiant séquentiel : seulement
`<jeton aléatoire>.<signature>`. La signature permet de rejeter immédiatement un QR altéré
(sans requête en base) ; l'autorité reste le backend qui retrouve le billet par son jeton.
"""
import hashlib
import hmac
import io
import secrets

import qrcode
from django.conf import settings

REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans caractères ambigus (0/O, 1/I)


def new_token():
    return secrets.token_urlsafe(18)


def new_reference():
    return "TKT-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(8))


def _sig(token):
    key = settings.QR_SIGNING_KEY.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()[:12]


def build_payload(token):
    return f"{token}.{_sig(token)}"


def parse_payload(payload):
    """Retourne le jeton si la signature est valide, sinon None."""
    if not payload or not isinstance(payload, str) or len(payload) > 120:
        return None
    token, sep, sig = payload.strip().rpartition(".")
    if not sep or not token or not hmac.compare_digest(sig, _sig(token)):
        return None
    return token


def qr_png_bytes(payload, box_size=8):
    img = qrcode.QRCode(box_size=box_size, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    img.add_data(payload)
    img.make(fit=True)
    buf = io.BytesIO()
    img.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()

from .models import AuditLog

_SENSITIVE_KEYS = {"password", "token", "secret", "authorization", "qr_token", "access", "refresh"}


def _clean(meta):
    return {k: v for k, v in (meta or {}).items() if k.lower() not in _SENSITIVE_KEYS}


def log(action, *, tenant=None, actor=None, entity="", entity_id="", **metadata):
    return AuditLog.objects.create(
        tenant=tenant,
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id or ""),
        metadata=_clean(metadata),
    )

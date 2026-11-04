from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class BusinessError(Exception):
    """Erreur métier explicite renvoyée au client avec un code stable."""

    def __init__(self, message, code="business_error", status_code=status.HTTP_409_CONFLICT):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def api_exception_handler(exc, context):
    if isinstance(exc, BusinessError):
        return Response({"detail": exc.message, "code": exc.code}, status=exc.status_code)
    if isinstance(exc, DjangoValidationError):
        return Response({"detail": "; ".join(exc.messages), "code": "validation_error"}, status=400)
    return exception_handler(exc, context)

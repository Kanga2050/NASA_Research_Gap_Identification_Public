from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
        if not key:
            raise ImproperlyConfigured(
                "DJANGO_FIELD_ENCRYPTION_KEY must be set to read/write encrypted "
                "fields (AgentSettings.gemini_api_key, ExternalApiSettings.openalex_api_key)."
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


class EncryptedCharField(models.CharField):
    """CharField that is encrypted at rest with Fernet (AES-128-CBC + HMAC).

    These are third-party API keys the app must send on outbound requests, so
    (unlike a password) they need to be recovered in cleartext later -- this is
    reversible encryption, not a one-way hash.
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return _get_fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Row written before encryption was introduced; self-heals on next save().
            return value

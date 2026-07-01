import hashlib
import secrets

from django.utils import timezone

from .models import ApiKey


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def create_api_key(user, name: str) -> tuple[ApiKey, str]:
    raw_key = generate_api_key()
    hashed_key = hash_api_key(raw_key)
    prefix = raw_key[:10]
    api_key = ApiKey.objects.create(
        user=user,
        name=name,
        prefix=prefix,
        hashed_key=hashed_key,
    )
    api_key.last_used_at = timezone.now()
    api_key.save(update_fields=["last_used_at"])
    return api_key, raw_key


def resolve_api_key(raw_key: str) -> ApiKey | None:
    hashed_key = hash_api_key(raw_key)
    try:
        api_key = ApiKey.objects.select_related("user").get(hashed_key=hashed_key)
    except ApiKey.DoesNotExist:
        return None

    if not api_key.is_active:
        return None

    api_key.last_used_at = timezone.now()
    api_key.save(update_fields=["last_used_at"])
    return api_key
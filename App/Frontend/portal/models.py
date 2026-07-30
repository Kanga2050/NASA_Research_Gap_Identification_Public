from django.conf import settings
from django.db import models
from django.utils import timezone

from .crypto_fields import EncryptedCharField


class ApiKey(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=12, unique=True)
    hashed_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def revoke(self) -> None:
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])

    def __str__(self) -> str:
        return f"{self.user.username}:{self.name}"


class TaskRecord(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        WORKING = "working", "Working"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_records")
    task_id = models.CharField(max_length=36, unique=True)
    function_name = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    args_json = models.JSONField(default=list, blank=True)
    kwargs_json = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.task_id}:{self.function_name}:{self.status}"


class UserStorageProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="storage_profile")
    root_name = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"storage:{self.user.username}"


class AgentSettings(models.Model):
    """Per-user configuration for the dashboard assistant: the user's own Gemini
    API key (needed to call the model) and the model they want it to use."""

    class GeminiModel(models.TextChoices):
        FLASH = "gemini-2.5-flash", "Gemini 2.5 Flash"
        FLASH_LITE = "gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite"
        PRO = "gemini-2.5-pro", "Gemini 2.5 Pro"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_settings")
    gemini_api_key = EncryptedCharField(max_length=500, blank=True)
    model = models.CharField(max_length=64, choices=GeminiModel.choices, default=GeminiModel.FLASH)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def has_key(self) -> bool:
        return bool(self.gemini_api_key)

    def __str__(self) -> str:
        return f"agent:{self.user.username}"


class ExternalApiSettings(models.Model):
    """Per-user credentials for the third-party data sources the *pipeline* calls.

    Kept separate from AgentSettings because these keys belong to background
    pipeline functions (the OpenAlex scraper), not to the dashboard assistant.
    Every key here is optional: the scrapers all work anonymously, a key only
    buys a higher rate limit.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="external_api_settings"
    )
    openalex_api_key = EncryptedCharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def has_openalex_key(self) -> bool:
        return bool(self.openalex_api_key)

    def __str__(self) -> str:
        return f"external-api:{self.user.username}"
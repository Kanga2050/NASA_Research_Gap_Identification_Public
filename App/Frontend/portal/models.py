from django.conf import settings
from django.db import models
from django.utils import timezone


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
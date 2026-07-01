from django.contrib import admin

from .models import ApiKey, TaskRecord, UserStorageProfile


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "prefix", "created_at", "last_used_at", "revoked_at")
    list_filter = ("revoked_at", "created_at")
    search_fields = ("user__username", "name", "prefix")


@admin.register(TaskRecord)
class TaskRecordAdmin(admin.ModelAdmin):
    list_display = ("task_id", "user", "function_name", "status", "created_at", "updated_at")
    list_filter = ("status", "function_name", "created_at")
    search_fields = ("task_id", "user__username", "function_name")


@admin.register(UserStorageProfile)
class UserStorageProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "root_name", "created_at")
    search_fields = ("user__username", "root_name")
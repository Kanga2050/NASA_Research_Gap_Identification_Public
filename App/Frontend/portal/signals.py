from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from App.Frontend.webapp.storage import (
    user_csv_root,
    user_html_root,
    user_task_root,
    user_template_root,
)

from .models import UserStorageProfile


User = get_user_model()


@receiver(post_save, sender=User)
def ensure_user_storage(sender, instance, created, **kwargs):
    if not created:
        return

    UserStorageProfile.objects.get_or_create(
        user=instance,
        defaults={"root_name": f"user_{instance.id}"},
    )
    # Provision the (empty) per-user storage folders. New accounts no longer get
    # starter CSVs auto-copied; users pull CSVs/HTML/templates from the shared
    # public library on demand from the Dashboard instead.
    user_csv_root(instance)
    user_html_root(instance)
    user_task_root(instance)
    user_template_root(instance)

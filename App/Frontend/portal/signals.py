import shutil
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from App.Frontend.webapp.storage import user_csv_root, user_html_root, user_task_root

from .models import UserStorageProfile


User = get_user_model()

STARTER_CSV_DIR = settings.BASE_DIR / "App" / "Backend" / "CSVs"


def _copy_starter_csvs(csv_root):
    if not STARTER_CSV_DIR.exists():
        return
    for source_path in STARTER_CSV_DIR.glob("*.csv"):
        destination = csv_root / source_path.name
        if destination.exists():
            continue
        try:
            shutil.copy2(source_path, destination)
        except OSError:
            pass


@receiver(post_save, sender=User)
def ensure_user_storage(sender, instance, created, **kwargs):
    if not created:
        return

    UserStorageProfile.objects.get_or_create(
        user=instance,
        defaults={"root_name": f"user_{instance.id}"},
    )
    csv_root = user_csv_root(instance)
    user_html_root(instance)
    user_task_root(instance)

    # The starter CSVs can be large, so copy them in the background rather
    # than blocking account creation (e.g. the signup request) until it's done.
    threading.Thread(target=_copy_starter_csvs, args=(csv_root,), daemon=True).start()
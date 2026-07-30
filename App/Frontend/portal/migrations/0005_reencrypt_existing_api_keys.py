from django.db import migrations


def reencrypt(apps, schema_editor):
    # AgentSettings/ExternalApiSettings.gemini_api_key & openalex_api_key were plaintext
    # CharFields before 0004; EncryptedCharField.from_db_value() falls back to returning
    # the raw value when it isn't a valid Fernet token, so reading + re-saving each row
    # here is enough to bring pre-existing plaintext values under encryption.
    AgentSettings = apps.get_model("portal", "AgentSettings")
    ExternalApiSettings = apps.get_model("portal", "ExternalApiSettings")

    for obj in AgentSettings.objects.exclude(gemini_api_key=""):
        obj.save(update_fields=["gemini_api_key"])

    for obj in ExternalApiSettings.objects.exclude(openalex_api_key=""):
        obj.save(update_fields=["openalex_api_key"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0004_alter_agentsettings_gemini_api_key_and_more"),
    ]

    operations = [
        migrations.RunPython(reencrypt, noop_reverse),
    ]

from __future__ import annotations

from django.db import migrations, models


def _backfill_method_booleans(apps, schema_editor):
    """Translate the old mfa_method enum into the two new booleans."""
    User = apps.get_model("accounts", "User")
    User.objects.filter(mfa_enabled=True, mfa_method="totp").update(mfa_totp_enabled=True)
    User.objects.filter(mfa_enabled=True, mfa_method="email").update(mfa_email_enabled=True)


def _noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_mfa_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="mfa_totp_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="mfa_email_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(_backfill_method_booleans, _noop_reverse),
        migrations.RemoveField(
            model_name="user",
            name="mfa_method",
        ),
    ]

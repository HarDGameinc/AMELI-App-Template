from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def _backfill_existing_totp_users(apps, schema_editor):
    """Existing enabled users were enrolled with TOTP. Tag them so the
    login flow picks the right verification UI after this migration.
    """
    User = apps.get_model("accounts", "User")
    User.objects.filter(mfa_enabled=True).update(mfa_method="totp")


def _noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_mfa"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="mfa_method",
            field=models.CharField(
                blank=True,
                choices=[("totp", "App de autenticacion"), ("email", "Email")],
                default="",
                max_length=10,
            ),
        ),
        migrations.RunPython(_backfill_existing_totp_users, _noop_reverse),
        migrations.CreateModel(
            name="MFAEmailChallenge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code_hash", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_challenges",
                        to="accounts.user",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]

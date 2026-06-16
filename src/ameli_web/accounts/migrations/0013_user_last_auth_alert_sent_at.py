"""Add ``User.last_auth_alert_sent_at`` to anchor the cooldown of the
auth-failures alert email (ASVS V2.2.3 / roadmap #2).

No backfill required — every row defaults to NULL ("no alert has ever
fired") so the very next lockout that crosses the threshold will
deliver the first alert for that user.
"""
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_mfa_secret_encrypt"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="last_auth_alert_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

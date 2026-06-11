from __future__ import annotations

from django.conf import settings
from django.contrib.auth.hashers import Argon2PasswordHasher


class ConfigurableArgon2Hasher(Argon2PasswordHasher):
    """Argon2id with tunable work factors read from Django settings.

    The defaults are django's own (and a reasonable baseline for a
    modern x86 server). The point of this subclass is that an operator
    can dial the work UP on beefy hardware — protecting against an
    offline GPU-cluster attacker who steals the hash table — without
    forking the Django source.

    OWASP's current recommendation (cheat sheet, 2024) for Argon2id is
    one of:

    * m=46 MiB, t=1, p=1
    * m=19 MiB, t=2, p=1
    * m=12 MiB, t=3, p=1

    Django's defaults (m=100 MiB, t=2, p=8) sit above the OWASP curve
    on memory but slightly below on iterations + use more parallelism.
    That trade-off favours a server that can spare RAM, which matches
    AMELI deploys; we leave it as the floor and let the operator
    raise it.

    Environment overrides (read into the corresponding settings):

    * ``AMELI_APP_ARGON2_TIME_COST``     -> settings.ARGON2_TIME_COST
    * ``AMELI_APP_ARGON2_MEMORY_COST``   -> settings.ARGON2_MEMORY_COST
    * ``AMELI_APP_ARGON2_PARALLELISM``   -> settings.ARGON2_PARALLELISM

    Because Django checks ``hasher.must_update(encoded)`` against the
    live class attributes on every successful login, bumping a value
    here triggers an opportunistic re-hash for every user on their next
    sign-in — no downtime, no migration.
    """

    @property
    def time_cost(self):  # type: ignore[override]
        return int(getattr(settings, "ARGON2_TIME_COST", 2))

    @property
    def memory_cost(self):  # type: ignore[override]
        return int(getattr(settings, "ARGON2_MEMORY_COST", 102400))

    @property
    def parallelism(self):  # type: ignore[override]
        return int(getattr(settings, "ARGON2_PARALLELISM", 8))

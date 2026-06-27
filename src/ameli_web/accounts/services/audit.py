"""Audit chain: HMAC-stamped append-only log + rotation tooling.

Extracted from the monolithic services.py on 2026-06-27 (PC-1 step 2).
The public API is unchanged: callers continue to ``from
ameli_web.accounts.services import record_audit, verify_audit_chain,
rotate_audit_key, apply_audit_key_to_env_file`` because
``services/__init__.py`` re-exports the names.

Other audit-related helpers (queryset filters, serialisers, admin
pagination) still live in ``services/__init__.py`` and will move in
a later iteration alongside the admin-view domain.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from ameli_web.audit.models import AuditEvent


def _audit_hmac_key() -> bytes:
    """Resolve the audit HMAC secret. An empty value disables chaining
    (rows still write, just without an integrity stamp) — useful in
    dev where the operator may not want to pin a key yet."""
    from django.conf import settings as django_settings

    raw = getattr(django_settings, "AUDIT_HMAC_KEY", "") or ""
    return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)


def _audit_canonical(*, prev_hmac: str, action: str, actor_username: str,
                     target_username: str, payload: dict, created_at) -> bytes:
    """Stable byte serialisation used as input to HMAC. ``sort_keys`` and
    a fixed separator keep the JSON representation deterministic; the
    ISO timestamp is normalised to UTC.

    We round-trip the payload through ``DjangoJSONEncoder`` + ``json.loads``
    before hashing so a value the caller passes in a richer Python type
    (``Decimal``, ``datetime``, ``UUID``, ``tuple``) lands in its JSON
    form before HMAC — the same form the DB will round-trip back on
    verify. Without this, ``record_audit`` hashed the in-memory dict
    while ``verify_audit_chain`` re-hashed the JSON-decoded version
    and reported a phantom tamper on the affected row.
    """
    import json

    from django.core.serializers.json import DjangoJSONEncoder

    raw = payload or {}
    payload_blob = json.dumps(
        json.loads(json.dumps(raw, cls=DjangoJSONEncoder)),
        sort_keys=True,
        separators=(",", ":"),
    )
    ts = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    return "|".join([
        prev_hmac,
        action,
        actor_username,
        target_username,
        payload_blob,
        ts,
    ]).encode("utf-8")


def _audit_hmac(*, key: bytes, prev_hmac: str, action: str, actor_username: str,
                target_username: str, payload: dict, created_at) -> str:
    import hashlib
    import hmac as hmac_lib

    body = _audit_canonical(
        prev_hmac=prev_hmac,
        action=action,
        actor_username=actor_username,
        target_username=target_username,
        payload=payload,
        created_at=created_at,
    )
    return hmac_lib.new(key, body, hashlib.sha256).hexdigest()


def _normalise_audit_payload(payload: dict | None) -> dict:
    """Round-trip the payload through ``DjangoJSONEncoder`` + ``json.loads``
    so a value the caller passes in a richer Python type (``Decimal``,
    ``datetime``, ``UUID``, ``tuple``) lands as the JSON form the DB
    will round-trip back on verify. Without this normalisation,
    ``record_audit`` hashed the in-memory dict while ``verify_audit_chain``
    re-hashed the JSON-decoded version and reported a phantom tamper
    on the affected row (and the INSERT itself fails for some types
    because the default JSONField encoder cannot serialise them).
    """
    import json

    from django.core.serializers.json import DjangoJSONEncoder

    return json.loads(json.dumps(payload or {}, cls=DjangoJSONEncoder))


def record_audit(action: str, *, actor=None, target_username: str | None = None, payload: dict[str, Any] | None = None) -> AuditEvent:
    """Write an audit row, optionally stamped with a per-row HMAC that
    chains back to the previous row.

    The chain lookup + write happen inside a ``transaction.atomic`` with
    ``select_for_update`` on the latest row so concurrent writers
    serialise: every committed row references the correct
    ``prev_hmac``. When ``AUDIT_HMAC_KEY`` is unset the chain stays
    empty and the row is written without an integrity stamp, so
    operators that never pin a key still see the audit log work.
    """
    from django.db import transaction

    from ameli_web.request_id import get_request_id

    actor_username = getattr(actor, "username", None) or ""
    target = target_username or ""
    payload_dict = _normalise_audit_payload(payload)
    # Stamp the audit row with the current request id (if any) so the
    # operator can correlate a single user action across multiple
    # log lines and audit events. Outside an HTTP request the value
    # is empty and we skip injecting the key.
    rid = get_request_id()
    if rid and "request_id" not in payload_dict:
        payload_dict["request_id"] = rid
    key = _audit_hmac_key()

    if not key:
        return AuditEvent.objects.create(
            actor_username=actor_username,
            target_username=target,
            action=action,
            payload=payload_dict,
        )

    with transaction.atomic():
        last = (
            AuditEvent.objects.select_for_update(skip_locked=False)
            .order_by("-id")
            .first()
        )
        prev_hmac = (last.hmac if last is not None else "") or ""
        event = AuditEvent.objects.create(
            actor_username=actor_username,
            target_username=target,
            action=action,
            payload=payload_dict,
            prev_hmac=prev_hmac,
        )
        # ``auto_now_add`` fills in ``created_at`` on insert; refresh so
        # the HMAC is computed against the value the DB actually stored.
        event.refresh_from_db(fields=["created_at"])
        event.hmac = _audit_hmac(
            key=key,
            prev_hmac=prev_hmac,
            action=event.action,
            actor_username=event.actor_username,
            target_username=event.target_username,
            payload=event.payload,
            created_at=event.created_at,
        )
        event.save(update_fields=["hmac"])
        return event


def verify_audit_chain(
    *,
    start_id: int | None = None,
    stop_id: int | None = None,
    key_override: bytes | str | None = None,
) -> dict[str, Any]:
    """Walk the audit chain in id order and report tampering.

    Returns a dict ``{ok, checked, first_break, broken_id, broken_reason}``
    that the ``verify-audit`` CLI surfaces. Rows written before the
    HMAC key was configured (no stored ``hmac``) are skipped — they are
    pre-chain history, not corruption.

    ``key_override`` lets callers (notably the rotation flow) verify a
    chain against a key that is not the one currently in settings.
    """
    if key_override is None:
        key = _audit_hmac_key()
    elif isinstance(key_override, str):
        key = key_override.encode("utf-8")
    else:
        key = bytes(key_override)
    if not key:
        return {
            "ok": False,
            "error": "AUDIT_HMAC_KEY is not configured; cannot verify chain.",
        }

    queryset = AuditEvent.objects.order_by("id")
    if start_id is not None:
        queryset = queryset.filter(id__gte=start_id)
    if stop_id is not None:
        queryset = queryset.filter(id__lte=stop_id)

    expected_prev = ""
    checked = 0
    first_break = None
    for row in queryset.iterator(chunk_size=500):
        if not row.hmac:
            # Legacy (pre-chain) row. Reset the expected prev so newer
            # chained rows aren't blamed for the gap.
            expected_prev = ""
            continue
        if row.prev_hmac != expected_prev:
            first_break = {
                "id": row.id,
                "reason": "prev_hmac mismatch",
                "expected": expected_prev,
                "found": row.prev_hmac,
            }
            break
        expected_hmac = _audit_hmac(
            key=key,
            prev_hmac=row.prev_hmac,
            action=row.action,
            actor_username=row.actor_username,
            target_username=row.target_username,
            payload=row.payload,
            created_at=row.created_at,
        )
        if expected_hmac != row.hmac:
            first_break = {
                "id": row.id,
                "reason": "hmac mismatch",
                "expected": expected_hmac,
                "found": row.hmac,
            }
            break
        expected_prev = row.hmac
        checked += 1

    if first_break is None:
        return {"ok": True, "checked": checked}
    return {
        "ok": False,
        "checked": checked,
        "broken_id": first_break["id"],
        "broken_reason": first_break["reason"],
        "expected": first_break.get("expected", ""),
        "found": first_break.get("found", ""),
    }


def rotate_audit_key(*, from_key: str, to_key: str) -> dict[str, Any]:
    """Re-stamp the audit chain with a fresh HMAC key.

    Use case: the old key was compromised, or an operator wants to
    rotate per policy. The naive approach (just change the env var)
    would invalidate every historical hmac. This helper preserves
    verifiability by:

    1. Verifying the chain end-to-end with the OLD key. Refuse to
       rotate if the chain is already broken — we'd be papering over
       tampering, not rotating cleanly.
    2. Walking every chained row in id order, recomputing the hmac
       with the NEW key, and chaining each new value through
       ``prev_hmac``. Legacy rows (hmac="") are skipped.
    3. Writing a final ``audit_key_rotated`` row that pins the
       transition (audit-of-audit) — it carries the NEW key already,
       so it's the first row of the post-rotation chain.

    All of step 2 happens inside one ``transaction.atomic`` so a
    failure mid-walk leaves the chain in its original state.

    The operator still has to update ``AMELI_APP_AUDIT_HMAC_KEY`` in
    the env file and restart the service AFTER calling this — the
    rotation re-stamps the database; the running process keeps its
    in-memory key until restart.
    """
    from django.db import transaction

    if not from_key:
        return {"ok": False, "error": "from_key is required"}
    if not to_key:
        return {"ok": False, "error": "to_key is required"}
    if from_key == to_key:
        return {"ok": False, "error": "to_key must differ from from_key"}

    # Step 1: verify the chain still walks under the old key.
    pre = verify_audit_chain(key_override=from_key)
    if not pre.get("ok"):
        return {
            "ok": False,
            "error": (
                "refuse to rotate: chain under from_key is already broken "
                "(verify it manually before rotating)"
            ),
            "verify_result": pre,
        }

    new_key_bytes = to_key.encode("utf-8") if isinstance(to_key, str) else bytes(to_key)

    with transaction.atomic():
        # Re-stamp each chained row with the new key, preserving the
        # canonical (action, actor, target, payload, created_at) tuple
        # but flowing the new hmacs through prev_hmac.
        queryset = AuditEvent.objects.order_by("id")
        new_prev = ""
        rotated = 0
        for row in queryset.iterator(chunk_size=500):
            if not row.hmac:
                # Legacy (pre-chain) row. Leave it alone and reset prev
                # so the next chained row starts fresh.
                new_prev = ""
                continue
            new_hmac = _audit_hmac(
                key=new_key_bytes,
                prev_hmac=new_prev,
                action=row.action,
                actor_username=row.actor_username,
                target_username=row.target_username,
                payload=row.payload,
                created_at=row.created_at,
            )
            AuditEvent.objects.filter(pk=row.pk).update(
                prev_hmac=new_prev, hmac=new_hmac,
            )
            new_prev = new_hmac
            rotated += 1
        # Audit-of-audit: write the rotation event using the NEW key so
        # it becomes the next link of the post-rotation chain.

        rotation_event = AuditEvent.objects.create(
            action="audit_key_rotated",
            target_username="",
            payload={"rotated_rows": rotated},
            prev_hmac=new_prev,
        )
        rotation_event.refresh_from_db(fields=["created_at"])
        rotation_event.hmac = _audit_hmac(
            key=new_key_bytes,
            prev_hmac=new_prev,
            action=rotation_event.action,
            actor_username=rotation_event.actor_username,
            target_username=rotation_event.target_username,
            payload=rotation_event.payload,
            created_at=rotation_event.created_at,
        )
        rotation_event.save(update_fields=["hmac"])

    # Step 3: confirm the chain verifies under the new key.
    post = verify_audit_chain(key_override=to_key)
    ok = bool(post.get("ok"))
    result: dict[str, Any] = {
        "ok": ok,
        "rotated": rotated + 1,
        "verify_result": post,
    }
    if ok:
        # Make the post-rotation step impossible to miss. The DB is now
        # signed with to_key but the running process still holds from_key
        # in memory, so the operator MUST update the env and restart.
        result["next_steps"] = [
            "DB chain re-stamped with to_key; running process still uses from_key.",
            "Update AMELI_APP_AUDIT_HMAC_KEY in the env file to the new value.",
            "Restart the api service so the in-memory key matches the DB.",
            "Re-run `ameli-app verify-audit` after the restart to confirm.",
        ]
    return result


def apply_audit_key_to_env_file(env_path: str, new_key: str) -> dict[str, Any]:
    """Atomically replace AMELI_APP_AUDIT_HMAC_KEY=... in an env file.

    Used by ``rotate-audit-key --apply-env`` so the post-rotation env
    update is not a manual ``sed`` the operator can typo. Writes a temp
    file in the same directory then renames, so a crash mid-write never
    leaves the env file truncated. After the rename the parent
    directory is fsynced so the rename hits stable storage — without
    that, a power loss between the rename and the next sync can lose
    the new content even though the file system reported success.

    Symlinks at the target path are rejected at the syscall level
    (``O_NOFOLLOW``) — no TOCTOU window between an ``islink`` check
    and the read.

    Preserves file mode if the target already exists. Refuses to run if
    ``new_key`` is empty (defense against the exact bug observed during
    the #6 verification: a shell variable typo blanked the env value),
    contains a newline or carriage return (would inject extra env
    variables), or contains an ``=`` (would corrupt the line shape).
    """
    import errno

    if not new_key:
        return {"ok": False, "error": "new_key is empty; refusing to write env file"}
    if any(ch in new_key for ch in ("\n", "\r", "=")):
        return {
            "ok": False,
            "error": "new_key contains newline/carriage-return/'='; refusing to write env file",
        }

    # O_NOFOLLOW makes the kernel reject a symlink at the final path
    # component. Combined with the same-directory tempfile + rename
    # pattern below, an attacker who plants a symlink at env_path
    # cannot redirect the write — neither the read nor the rename
    # will traverse it.
    try:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(env_path, os.O_RDONLY | nofollow)
    except FileNotFoundError:
        return {"ok": False, "error": f"env file not found: {env_path}"}
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return {"ok": False, "error": f"refusing to write through symlink: {env_path}"}
        return {"ok": False, "error": f"cannot read env file: {exc}"}
    try:
        with os.fdopen(fd, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return {"ok": False, "error": f"cannot read env file: {exc}"}

    replaced = False
    new_lines = []
    for line in lines:
        if line.startswith("AMELI_APP_AUDIT_HMAC_KEY="):
            new_lines.append(f"AMELI_APP_AUDIT_HMAC_KEY={new_key}\n")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"AMELI_APP_AUDIT_HMAC_KEY={new_key}\n")

    try:
        original_mode = os.stat(env_path).st_mode & 0o777
    except OSError:
        original_mode = 0o600
    env_dir = os.path.dirname(os.path.abspath(env_path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".app.env.", dir=env_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(new_lines)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, env_path)
        # fsync the parent directory so the rename is durable across
        # a power loss. Only meaningful on platforms with O_DIRECTORY;
        # silently skipped on others (Windows, etc.).
        if hasattr(os, "O_DIRECTORY"):
            try:
                dir_fd = os.open(env_dir, os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                # Best-effort: the rename already succeeded.
                pass
    except OSError as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return {"ok": False, "error": f"cannot write env file: {exc}"}
    return {"ok": True, "env_path": env_path, "appended": not replaced}

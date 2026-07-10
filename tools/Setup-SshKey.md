# `Setup-SshKey.ps1` — manual

A reusable, idempotent PowerShell helper that sets up an SSH/SFTP key on a
**Windows workstation** for reaching a server that runs this template
(SSH is key-only — see [`docs/SERVER_HARDENING.md`](../docs/SERVER_HARDENING.md) §4).
It covers three clients from one key: **PowerShell (OpenSSH)**, **PuTTY**
(`.ppk`), and **FileZilla** (SFTP).

The script itself is self-documenting: `Get-Help .\tools\Setup-SshKey.ps1 -Full`.

---

## What it does

1. Generates an **ed25519** key pair under `%USERPROFILE%\.ssh\` (you type the
   passphrase at the prompt).
2. Prints the **public key** and the exact server-side command to authorize it.
3. Optionally converts the private key to a **PuTTY `.ppk`** (opens PuTTYgen).
4. Prints **next-step** commands for PowerShell, PuTTY/Pageant and FileZilla.

**Safe by design**

- **Idempotent** — if the key already exists it *skips generation* and just
  re-prints the public key + instructions. It never overwrites unless you pass
  `-Force`.
- The **private key never leaves the machine**, and the script **never handles
  your passphrase** — `ssh-keygen` prompts you directly.

---

## Prerequisites

| Tool | Needed for | Where |
|------|-----------|-------|
| Windows **OpenSSH Client** (`ssh`, `ssh-keygen`) | key generation + PowerShell SSH | built-in on Win10/11 (Settings → Optional features), or `C:\Windows\System32\OpenSSH\` |
| **PuTTY** (`puttygen.exe`, `pageant.exe`) | `.ppk` + agent | https://www.putty.org (`C:\Program Files\PuTTY\`) |
| **FileZilla** | SFTP | https://filezilla-project.org |

> **Execution policy**: if the script is blocked from running, invoke it once as
> `powershell -ExecutionPolicy Bypass -File .\tools\Setup-SshKey.ps1 ...`
> (or `Unblock-File .\tools\Setup-SshKey.ps1`).

---

## Quick start

```powershell
# From the repo root:
.\tools\Setup-SshKey.ps1 -ServerHost 10.100.100.16 -MakePpk
```

Then follow the printed steps (authorize on the server → test → PuTTY → FileZilla).

---

## Parameters

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `-KeyName` | `id_ed25519` | Base file name under `%USERPROFILE%\.ssh`. Use a distinct name for a second host/key. |
| `-Comment` | `<user>@<computer>` | Key label (shown in `authorized_keys`). |
| `-ServerHost` | *(empty)* | Server host/IP. When set, printed commands are copy-ready. |
| `-ServerUser` | `root` | Remote user for the printed commands. |
| `-Port` | `22` | SSH port. |
| `-MakePpk` | *(off)* | Also open PuTTYgen to produce the `.ppk`. |
| `-Force` | *(off)* | Regenerate even if the key exists (**overwrites** — deliberate use only). |

---

## Full walkthrough

### 1. Generate the key

```powershell
.\tools\Setup-SshKey.ps1 -ServerHost <server-ip> -MakePpk
```

- You are prompted for a **passphrase** (twice). Choose a strong one and store
  it safely — without it the key is unusable and there is no recovery.
- Files created: `%USERPROFILE%\.ssh\id_ed25519` (private) and `id_ed25519.pub`
  (public).
- If the key already exists, generation is skipped (nothing is overwritten).

### 2. Authorize the public key on the server

The script prints exactly this (with your real key). Run it **from a session
that is already authorized** on the server (another machine, or your current
open session) — root is key-only, so there is no password fallback:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAA... <user>@<computer>' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

> ⚠️ **Keep your current server session open** until step 3 confirms the new key
> logs in — so a mistake can't lock you out.

### 3. Test PowerShell (OpenSSH)

In a new terminal:

```powershell
ssh -i "$env:USERPROFILE\.ssh\id_ed25519" <user>@<server-ip>
```

- It asks for your **passphrase** (not a server password → confirms key-only).
- First connection asks to trust the host key — verify the fingerprint, then
  `yes`.
- You can omit `-i`; OpenSSH uses `~/.ssh/id_ed25519` by default.

### 4. PuTTY

If you ran with `-MakePpk`, PuTTYgen opens with the key loaded:

1. Enter the passphrase.
2. **Save private key** → `%USERPROFILE%\.ssh\id_ed25519.ppk`.

Load it once into **Pageant** so you don't retype the passphrase each connect:

```powershell
& "C:\Program Files\PuTTY\pageant.exe" "$env:USERPROFILE\.ssh\id_ed25519.ppk"
```

Then in PuTTY: **Session** → Host `<user>@<server-ip>`, Port `22` → Open.

### 5. FileZilla (SFTP)

1. **Edit → Settings → Connection → SFTP → Add key file…** → select the
   `.ppk` (FileZilla supports `.ppk` natively; if you pick the OpenSSH
   `id_ed25519` it offers to convert).
2. **File → Site Manager → New site**: Protocol **SFTP**, Host `<server-ip>`,
   Port `22`, User `<user>`, Logon Type **Key file** (or *Interactive*).
3. **Connect** → passphrase is requested (or taken from Pageant).

---

## Examples

```powershell
# Default key, print the authorize command for a host, make the .ppk:
.\tools\Setup-SshKey.ps1 -ServerHost 10.100.100.16 -MakePpk

# A separate, named key for a different host/user:
.\tools\Setup-SshKey.ps1 -KeyName id_ameli_prod -Comment "hardg@hardgame1" -ServerHost srv.lan -ServerUser deploy

# Just re-print the public key + instructions (key already exists):
.\tools\Setup-SshKey.ps1 -ServerHost 10.100.100.16

# Full built-in help:
Get-Help .\tools\Setup-SshKey.ps1 -Full
```

---

## Security notes

- **One key per workstation** is fine; all three clients use the same private
  key. Use a distinct `-KeyName` only if you want separate keys per host/role.
- The passphrase is the last line of defence if the workstation is stolen —
  **always use one** for a key that grants server (root) access.
- The public key is safe to share/paste; the **private key** (`id_ed25519`,
  no `.pub`) and the `.ppk` must never leave the machine or enter git.
- Rotating/retiring a key = remove its line from the server's
  `~/.ssh/authorized_keys` and delete the local files.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `ssh-keygen not found` | Enable the **OpenSSH Client** optional feature (Settings → Apps → Optional features). |
| `Permission denied (publickey)` on connect | Public key not in `authorized_keys`, or wrong perms — `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`; confirm you're offering the right key (`ssh -i <path>`). |
| PuTTYgen not found (with `-MakePpk`) | Install PuTTY, or convert manually: `& "C:\Program Files\PuTTY\puttygen.exe" "<key>" -o "<key>.ppk"`. |
| Forgot the passphrase | No recovery. Regenerate with `-Force`, then re-authorize the new public key on the server. |
| FileZilla rejects the OpenSSH key | Point it at the `.ppk` instead (or let it convert on import). |
| Script won't run (execution policy) | `powershell -ExecutionPolicy Bypass -File .\tools\Setup-SshKey.ps1 ...`. |
| Want to start over cleanly | Delete `id_ed25519*` from `%USERPROFILE%\.ssh`, remove the old line from the server's `authorized_keys`, re-run. |

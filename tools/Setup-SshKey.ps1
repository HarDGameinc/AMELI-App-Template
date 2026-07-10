<#
.SYNOPSIS
    Set up an SSH/SFTP key on a Windows workstation for PowerShell (OpenSSH),
    PuTTY and FileZilla. Idempotent - never clobbers an existing key.

.DESCRIPTION
    Generates an ed25519 key pair (you type the passphrase at the prompt),
    prints the public key plus the exact server-side command to authorize it,
    optionally converts the private key to a PuTTY .ppk, and prints the
    PuTTY/Pageant + FileZilla setup steps.

    The private key never leaves this machine and the script never handles
    your passphrase (ssh-keygen prompts you directly). An existing key is
    left untouched unless you pass -Force.

    This is workstation tooling for reaching a server that runs this template
    (see docs/SERVER_HARDENING.md - SSH is key-only). It is generic: point it
    at any host/user/key name.

.PARAMETER KeyName
    Base file name under %USERPROFILE%\.ssh. Default: id_ed25519.

.PARAMETER Comment
    Key comment/label. Default: <user>@<computer>.

.PARAMETER ServerHost
    Optional server host/IP. When given, the printed commands are ready to copy.

.PARAMETER ServerUser
    Remote user for the printed connect/authorize commands. Default: root.

.PARAMETER Port
    SSH port. Default: 22.

.PARAMETER MakePpk
    Also convert the private key to .ppk for PuTTY (opens PuTTYgen so you can
    enter the passphrase and Save private key).

.PARAMETER Force
    Regenerate even if the key already exists (OVERWRITES - use deliberately).

.EXAMPLE
    .\Setup-SshKey.ps1 -ServerHost 10.100.100.16 -MakePpk
    Generate id_ed25519 (if missing), print the authorize command for that
    host, and open PuTTYgen to make the .ppk.

.EXAMPLE
    .\Setup-SshKey.ps1 -KeyName id_ameli_prod -Comment "hardg@hardgame1" -ServerHost srv.lan -ServerUser deploy
    A separate, named key for a different host/user.

.NOTES
    Re-running is safe: it skips generation when the key exists and just
    re-prints the public key + instructions.

.LINK
    tools/Setup-SshKey.md   (full manual: walkthrough, examples, troubleshooting)
#>
[CmdletBinding()]
param(
    [string]$KeyName    = "id_ed25519",
    [string]$Comment    = "$env:USERNAME@$env:COMPUTERNAME",
    [string]$ServerHost = "",
    [string]$ServerUser = "root",
    [int]   $Port       = 22,
    [switch]$MakePpk,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Find-Exe {
    param([string]$Name, [string[]]$Candidates)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in $Candidates) { if (Test-Path $c) { return $c } }
    return $null
}

# --- 1. Prereqs ---
$keygen = Find-Exe "ssh-keygen" @("C:\Windows\System32\OpenSSH\ssh-keygen.exe")
if (-not $keygen) {
    throw "ssh-keygen not found. Install the Windows OpenSSH Client (Settings > Optional features)."
}

$sshDir = Join-Path $env:USERPROFILE ".ssh"
if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Path $sshDir | Out-Null }

$keyPath = Join-Path $sshDir $KeyName
$pubPath = "$keyPath.pub"
$ppkPath = "$keyPath.ppk"

# --- 2. Generate (idempotent, no clobber) ---
if ((Test-Path $keyPath) -and -not $Force) {
    Write-Host "[skip] Key already exists: $keyPath  (use -Force to regenerate)" -ForegroundColor Yellow
} else {
    if ((Test-Path $keyPath) -and $Force) {
        Write-Host "[warn] -Force: overwriting $keyPath" -ForegroundColor Red
        Remove-Item $keyPath, $pubPath -ErrorAction SilentlyContinue
    }
    Write-Host "[gen]  ed25519 -> $keyPath" -ForegroundColor Cyan
    Write-Host "       You'll be prompted for a passphrase (recommended - this key grants server access)."
    & $keygen -t ed25519 -a 100 -C $Comment -f $keyPath
    if ($LASTEXITCODE -ne 0) { throw "ssh-keygen failed (exit $LASTEXITCODE)." }
}

if (-not (Test-Path $pubPath)) { throw "Public key not found: $pubPath" }
$pub = (Get-Content $pubPath -Raw).Trim()
$hostLabel = if ($ServerHost) { $ServerHost } else { "<SERVER_HOST>" }

# --- 3. Public key + server authorize command ---
Write-Host "`n=== PUBLIC KEY ($pubPath) ===" -ForegroundColor Green
Write-Host $pub
Write-Host "`n=== AUTHORIZE ON THE SERVER (run from an already-authorized session) ===" -ForegroundColor Green
Write-Host "mkdir -p ~/.ssh && chmod 700 ~/.ssh"
Write-Host ("echo '{0}' >> ~/.ssh/authorized_keys" -f $pub)
Write-Host "chmod 600 ~/.ssh/authorized_keys"

# --- 4. PuTTY .ppk (optional) ---
if ($MakePpk) {
    $puttygen = Find-Exe "puttygen" @(
        "C:\Program Files\PuTTY\puttygen.exe",
        "C:\Program Files (x86)\PuTTY\puttygen.exe"
    )
    if (-not $puttygen) {
        Write-Host "`n[ppk] PuTTYgen not found. Install PuTTY, then convert with:" -ForegroundColor Yellow
        Write-Host ('      & "C:\Program Files\PuTTY\puttygen.exe" "{0}" -o "{1}"' -f $keyPath, $ppkPath)
    } elseif ((Test-Path $ppkPath) -and -not $Force) {
        Write-Host "`n[ppk] Already exists: $ppkPath  (skip)" -ForegroundColor Yellow
    } else {
        Write-Host "`n[ppk] Opening PuTTYgen - enter your passphrase, then 'Save private key' -> $ppkPath" -ForegroundColor Cyan
        Start-Process $puttygen -ArgumentList ('"{0}"' -f $keyPath)
    }
}

# --- 5. Client instructions ---
Write-Host "`n=== NEXT STEPS ===" -ForegroundColor Green
Write-Host ('PowerShell (OpenSSH):  ssh -i "{0}" {1}@{2} -p {3}' -f $keyPath, $ServerUser, $hostLabel, $Port)
Write-Host ('PuTTY / Pageant:       & "C:\Program Files\PuTTY\pageant.exe" "{0}"' -f $ppkPath)
Write-Host ('                       then PuTTY Session: {0}@{1}  Port {2}' -f $ServerUser, $hostLabel, $Port)
Write-Host ('FileZilla (SFTP):      Settings > Connection > SFTP > Add key file -> {0}' -f $ppkPath)
Write-Host ('                       Site Manager: Protocol SFTP, Host {0}, Port {1}, User {2}, Logon "Key file"' -f $hostLabel, $Port, $ServerUser)
Write-Host "`nKeep your current server session open until the new key is verified to log in." -ForegroundColor Green

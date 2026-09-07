<#
.SYNOPSIS
    One-time automated first-run setup for the NUC (see SETUP.md / DEPLOY.md).

.DESCRIPTION
    Automates everything about NUC setup that CAN safely be automated:
      1. Installs Python and Git (via winget) if not already present.
      2. Clones the app repo onto the `production` branch (or leaves it alone if already
         cloned) - see DEPLOY.md for why the NUC runs a different branch than the dev PC.
      3. Scaffolds .env from .env.example and pauses for you to fill in real values.
      4. Adds a Windows Firewall rule scoped to your actual LAN subnet (auto-detected).
      5. Starts the server once and confirms the health check responds.

    Deliberately does NOT touch:
      - The router-side static IP / DHCP reservation (SETUP.md step 5) - no script has
        access to your router's admin UI.
      - Windows Task Scheduler entries for auto-start-on-boot and weekly backup
        (SETUP.md steps 8-9) - kept as manual GUI steps on purpose (see CLAUDE.md >
        Deployment Environment > Startup for why: scripting the "run whether user is
        logged on or not" boot task needs the account password handled non-interactively,
        which trades one kind of fragility for another).

    Re-run safe: every step checks current state first and skips what's already done.

.PARAMETER InstallPath
    Where to clone the app. Default C:\Apps\ShoppingApp.

.PARAMETER RepoUrl
    The private GitHub repo to clone. Default is this project's repo.
#>

param(
    [string]$InstallPath = "C:\Apps\ShoppingApp",
    [string]$RepoUrl = "https://github.com/WRooke/ShoppingApp.git"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  WARNING: $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  ERROR: $msg" -ForegroundColor Red }

# --- Require Administrator (needed for winget machine-wide installs + firewall rule) ---
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Re-launching elevated (this needs Administrator for installs + firewall)..." -ForegroundColor Yellow
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"",
                 "-InstallPath", "`"$InstallPath`"", "-RepoUrl", "`"$RepoUrl`"")
    Start-Process powershell -Verb RunAs -ArgumentList $argList
    exit
}

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# --- 1. Python + Git ---
Write-Step "Checking Python and Git"

$haveWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)

function Ensure-Tool($name, $checkCmd, $wingetId, $manualUrl) {
    if (Get-Command $checkCmd -ErrorAction SilentlyContinue) {
        Write-Ok "$name already installed."
        return $true
    }
    if (-not $haveWinget) {
        Write-Err "$name not found and winget isn't available on this NUC."
        Write-Host "  Install it manually from $manualUrl (tick 'Add to PATH' for Python), then re-run this script." -ForegroundColor Yellow
        return $false
    }
    Write-Host "  Installing $name via winget..."
    winget install --id $wingetId -e --source winget --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (Get-Command $checkCmd -ErrorAction SilentlyContinue) {
        Write-Ok "$name installed."
        return $true
    }
    Write-Err "$name install via winget didn't leave $checkCmd on PATH. Try a new terminal, or install manually from $manualUrl."
    return $false
}

$pythonOk = Ensure-Tool "Python" "py" "Python.Python.3.13" "https://www.python.org/downloads/windows/"
$gitOk    = Ensure-Tool "Git"    "git" "Git.Git"            "https://git-scm.com/download/win"

if (-not ($pythonOk -and $gitOk)) {
    Write-Err "Can't continue without both Python and Git. Install the missing one(s) and re-run."
    exit 1
}

# --- 2. Clone the repo ---
Write-Step "Getting the app onto this machine"

if (Test-Path (Join-Path $InstallPath ".git")) {
    Write-Ok "$InstallPath is already a git checkout - leaving it alone (use update.bat to update it)."
} else {
    $parent = Split-Path $InstallPath -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    if ((Test-Path $InstallPath) -and (Get-ChildItem $InstallPath -Force -ErrorAction SilentlyContinue)) {
        Write-Err "$InstallPath exists and isn't a git checkout, and isn't empty. Move it aside and re-run."
        exit 1
    }
    Write-Host "  Cloning $RepoUrl into $InstallPath ..."
    Write-Host "  (This is a private repo - a Git sign-in prompt/browser window is expected here.)" -ForegroundColor Yellow
    git clone $RepoUrl $InstallPath
    Write-Ok "Cloned."

    # The NUC always runs `production`, never whichever branch happens to be the repo's
    # default (see CLAUDE.md > Deferred Decisions > Git branching strategy and DEPLOY.md) -
    # scripts/update.py enforces this on every run, but check it here too so the very first
    # update.bat doesn't fail on something this script could have gotten right immediately.
    Push-Location $InstallPath
    git checkout production 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Cloned, but couldn't check out 'production' - does that branch exist on origin yet? See DEPLOY.md > One-time setup step 2."
        Pop-Location
        exit 1
    }
    Write-Ok "Checked out 'production'."
    Pop-Location
}

Set-Location $InstallPath

# --- 3. .env ---
Write-Step "Configuration (.env)"

if (Test-Path ".env") {
    Write-Ok ".env already exists - leaving it alone."
} else {
    Copy-Item ".env.example" ".env"
    Write-Host "  Created .env from .env.example. Opening it in Notepad -" -ForegroundColor Yellow
    Write-Host "  fill in real values (PORT is fine as-is for Phase 1; leave GEMINI_API_KEY /" -ForegroundColor Yellow
    Write-Host "  ANYLIST_* as placeholders until Phase 3 / Phase 5). Save and close Notepad to continue." -ForegroundColor Yellow
    Start-Process notepad.exe -ArgumentList ".env" -Wait
    Write-Ok ".env configured."
}

# --- 4. Firewall rule, scoped to the actual LAN subnet ---
Write-Step "Windows Firewall rule"

function Get-LocalSubnetCidr {
    $cfg = Get-NetIPConfiguration | Where-Object {
        $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up'
    } | Select-Object -First 1
    if (-not $cfg) { return $null }
    $ip = $cfg.IPv4Address.IPAddress
    $prefixLen = $cfg.IPv4Address.PrefixLength
    $ipBytes = ([System.Net.IPAddress]::Parse($ip)).GetAddressBytes()
    $maskInt = [uint32]([math]::Pow(2, 32) - [math]::Pow(2, 32 - $prefixLen))
    $maskBytes = [BitConverter]::GetBytes($maskInt)
    [Array]::Reverse($maskBytes)
    $netBytes = 0..3 | ForEach-Object { $ipBytes[$_] -band $maskBytes[$_] }
    return "$($netBytes -join '.')/$prefixLen"
}

$port = 8080
$envPortLine = Get-Content ".env" | Where-Object { $_ -match '^\s*PORT\s*=\s*(\d+)' }
if ($envPortLine -and $envPortLine -match '(\d+)') { $port = [int]$Matches[1] }

$subnet = Get-LocalSubnetCidr
if (-not $subnet) {
    Write-Warn "Couldn't auto-detect the LAN subnet - skipping the firewall rule. Add it manually (SETUP.md step 6)."
} else {
    $ruleName = "ShoppingApp $port"
    Write-Host "  Scoping to $subnet on port $port (Private profile only)."
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($existing) {
        $existing | Set-NetFirewallRule -Profile Private
        $existing | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $subnet
        Write-Ok "Updated existing rule '$ruleName'."
    } else {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort $port -Profile Private -RemoteAddress $subnet | Out-Null
        Write-Ok "Created firewall rule '$ruleName'."
    }
}

# --- 5. First start + health check ---
Write-Step "First start"

Write-Host "  Starting the server in a new window (creates the venv + installs dependencies - may take a minute)..."
Start-Process -FilePath ".\start.bat" -WorkingDirectory $InstallPath

$healthy = $false
$healthUrl = "http://127.0.0.1:$port/api/v1/health"
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 5
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
}

if ($healthy) {
    Write-Ok "Server is up: $healthUrl"
} else {
    Write-Warn "Server didn't respond at $healthUrl within 2 minutes. Check the server window for errors, and logs\app.log."
}

# --- Summary ---
Write-Step "Done - what's left (manual, on purpose)"
Write-Host "  1. Static IP: give this NUC a DHCP reservation in your router - see SETUP.md step 5."
Write-Host "  2. Firewall (done above) - re-check SETUP.md step 6 if your subnet ever changes."
Write-Host "  3. Auto-start on boot + weekly backup: Task Scheduler, GUI steps - SETUP.md steps 8-9."
Write-Host "  4. Reach it from a phone once the static IP is set - SETUP.md step 7."
Write-Host "`nFrom now on, ship updates with update.bat (see DEPLOY.md) - not this script again."

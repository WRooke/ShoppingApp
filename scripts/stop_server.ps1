# Stop the ShoppingApp server and make sure the port is actually free again.
# Called by stop.bat (itself called by update.bat). See
# docs/deployment-and-operations.md > "How an open phone learns the NUC was updated".
#
# Why this is more than "kill python.exe by command line" (what stop.bat used to do alone):
#  * Stop-Process failures were swallowed and "Done." printed regardless, so an old server that
#    could not be killed (a process owned by another account, e.g. the Task Scheduler one) kept
#    serving OLD code while the new one died on "address already in use".
#  * It now also stops whoever LISTENS on the app's port, whatever its command line says, reports
#    every failure, waits for the port to be free, and exits 1 if it is not.

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot

# The configured port: PORT in .env, else 8080 (same default as app/config.py).
$port = 8080
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    $line = Select-String -Path $envFile -Pattern '^\s*PORT\s*=\s*(\d+)' | Select-Object -First 1
    if ($line) { $port = [int]$line.Matches[0].Groups[1].Value }
}
if ($env:PORT -match '^\d+$') { $port = [int]$env:PORT }

$failed = @()

function Stop-One($procId, $why) {
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped PID $procId ($why)"
    } catch {
        # Killing the venv launcher stub takes its child interpreter down with it, so the second
        # PID is often already gone by the time we get to it - that is success, not a failure.
        if (-not (Get-Process -Id $procId -ErrorAction SilentlyContinue)) {
            Write-Host "PID $procId already gone ($why)"
        } else {
            $script:failed += $procId
            Write-Host "COULD NOT stop PID ${procId} ($why): $($_.Exception.Message)"
        }
    }
}

# 1. python.exe whose command line is this app (the venv launcher stub AND the real interpreter).
$byCmd = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'app\.main' -or $_.CommandLine -match 'uvicorn' })
if (-not $byCmd) { Write-Host 'No running ShoppingApp process found by command line.' }
foreach ($p in $byCmd) { Stop-One $p.ProcessId 'app.main/uvicorn' }

# 2. Whatever is still listening on the port (covers a differently-named launcher).
Start-Sleep -Milliseconds 500
$listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($id in $listeners) {
    if ($id -and $id -ne 0 -and $id -ne $PID) { Stop-One $id "listening on port $port" }
}

# 3. Wait for the port to actually be free.
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    $still = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if (-not $still) { Write-Host "Port $port is free."; exit 0 }
    Start-Sleep -Milliseconds 500
}

Write-Host ''
Write-Host "PROBLEM: port $port is still in use - the old server was NOT stopped."
if ($failed) { Write-Host ("Could not stop PID(s): " + ($failed -join ', ') + '. Try an elevated prompt, or end them in Task Manager.') }
Write-Host 'The new server cannot start until this is fixed.'
exit 1

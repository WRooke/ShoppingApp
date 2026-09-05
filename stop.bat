@echo off
setlocal
cd /d "%~dp0"

echo === ShoppingApp: stopping ===

rem Kill any python.exe whose command line is running this app / uvicorn.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'app\.main' -or $_.CommandLine -match 'uvicorn' };" ^
  "if (-not $p) { Write-Host 'No running ShoppingApp process found.'; exit 0 }" ^
  "foreach ($proc in $p) { Write-Host ('Stopping PID ' + $proc.ProcessId); Stop-Process -Id $proc.ProcessId -Force }"

echo Done.
endlocal

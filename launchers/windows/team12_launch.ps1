# Team 12 double-click launcher (Windows). Called by the .cmd files in this folder.
#   processing : Node-RED, SQLite, analytics, decision engine and the dashboard
#   device     : Company A/B replay (the IoT sensors) and the virtual line (the actuator)
#   stop       : stop everything these launchers started
# Both roles talk only through the free public HiveMQ broker (broker.hivemq.com).
param(
    [Parameter(Mandatory = $true)][ValidateSet("processing", "device", "stop")][string]$Role,
    [switch]$MlDriven
)
$env:PYTHONUNBUFFERED = "1"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
# The device role runs from a sibling copy, so both roles can also share one laptop
# (two roles in one folder would share logs\ and the stop request file).
$DeviceRoot = "$Root-device"

function Stop-Folder([string]$folder) {
    # Stop every python/node process whose command line points into $folder, children included.
    $all = @(Get-CimInstance Win32_Process)
    $hits = @($all | Where-Object {
        ($_.Name -in @("python.exe", "pythonw.exe", "node.exe")) -and $_.CommandLine -and
        $_.CommandLine.IndexOf($folder + "\", [StringComparison]::OrdinalIgnoreCase) -ge 0 })
    foreach ($p in $hits) {
        Write-Host ("  stopping " + $p.Name + " (PID " + $p.ProcessId + ")")
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    return $hits.Count
}

function Wait-Unlocked([string]$file) {
    # Node-RED or a database viewer can keep db\team12.db open for a moment after stopping.
    if (-not (Test-Path -LiteralPath $file)) { return $true }
    for ($i = 0; $i -lt 15; $i++) {
        try { $s = [IO.File]::Open($file, "Open", "ReadWrite", "None"); $s.Close(); return $true }
        catch { Start-Sleep -Seconds 1 }
    }
    return $false
}

function Invoke-Logged([string]$log, [scriptblock]$block) {
    & $block 2>&1 | Tee-Object -FilePath $log -Append
}

if ($Role -eq "stop") {
    Write-Host "Stopping Team 12 demo processes..."
    $n = (Stop-Folder $Root) + (Stop-Folder $DeviceRoot)
    Write-Host "Stopped $n process(es)."
    return
}

$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if ($Role -eq "processing") {
    Write-Host "Team 12 PROCESSING role - project folder: $Root"
    if ((Stop-Folder $Root) -gt 0) { Start-Sleep -Seconds 3 }
    Set-Location -LiteralPath $Root
    $log = Join-Path $logDir "launcher_processing.log"
    "=== setup $(Get-Date)" | Out-File $log -Encoding utf8
    if (-not (Test-Path ".venv\Scripts\python.exe") -or -not (Test-Path "nodered\node_modules\node-red\red.js")) {
        Write-Host "First run: installing Python and Node-RED packages (a few minutes)..."
        Invoke-Logged $log { powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 }
    }
    if (-not (Wait-Unlocked (Join-Path $Root "db\team12.db"))) {
        Write-Host ""
        Write-Host "db\team12.db is still in use by another program (a database viewer, or another demo window)." -ForegroundColor Yellow
        Write-Host "Close it, run 0_stop_everything.cmd, then start this again." -ForegroundColor Yellow
        return
    }
    "=== run $(Get-Date)" | Out-File $log -Append -Encoding utf8
    Write-Host "Starting. When you see 'Cloud laptop ready', open http://localhost:1880/ui"
    Invoke-Logged $log { .\.venv\Scripts\python.exe -u scripts\two_laptop.py cloud --broker public --reset-db }
    return
}

# device
Write-Host "Team 12 DEVICE role - running from: $DeviceRoot"
if ((Stop-Folder $DeviceRoot) -gt 0) { Start-Sleep -Seconds 2 }
Write-Host "Refreshing the device copy from $Root ..."
robocopy "$Root" "$DeviceRoot" /E /NFL /NDL /NJH /NJS /NP `
    /XD "$Root\.git" "$Root\.venv" "$Root\nodered\node_modules" "$Root\logs" "$Root\data\raw" `
    /XF team12.db events_clean.csv features.csv | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host "Copy to $DeviceRoot failed (robocopy code $LASTEXITCODE)." -ForegroundColor Red; return }
Set-Location -LiteralPath $DeviceRoot
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$log = Join-Path $DeviceRoot "logs\launcher_device.log"
"=== setup $(Get-Date)" | Out-File $log -Encoding utf8
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "First run: installing Python packages for the device role..."
    Invoke-Logged $log { powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_device_windows.ps1 }
}
"=== run $(Get-Date)" | Out-File $log -Append -Encoding utf8
if ($MlDriven) {
    Write-Host "ML-driven line: the active model's forecasts set the stage capacities."
    Invoke-Logged $log { .\.venv\Scripts\python.exe -u scripts\two_laptop.py device --broker public --manual-replay --line-speed 60 --ml-driven }
} else {
    Invoke-Logged $log { .\.venv\Scripts\python.exe -u scripts\two_laptop.py device --broker public --scenario slowdown --manual-replay --line-speed 40 }
}

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$pythonExecutable = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($version in @("-3.12", "-3")) {
        try {
            $candidate = (& py $version -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
            if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath $candidate)) {
                $pythonExecutable = $candidate
                break
            }
        } catch {}
    }
}
if (-not $pythonExecutable -and (Get-Command python -ErrorAction SilentlyContinue)) {
    try {
        $candidate = (& python -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath $candidate)) {
            $pythonExecutable = $candidate
        }
    } catch {}
}
$codexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not $pythonExecutable -and (Test-Path -LiteralPath $codexPython)) {
    $pythonExecutable = $codexPython
}
if (-not $pythonExecutable) {
    throw "Python 3.12 is required. Install it, then rerun this setup script."
}
Write-Host "Using Python: $pythonExecutable"
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    & $pythonExecutable -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create Python virtual environment" }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Python package installation failed" }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "Node.js and npm are required. Install Node.js, then rerun setup."
}
& npm.cmd install --prefix nodered --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "Node-RED package installation failed" }
Write-Host "Ready. Run: .\.venv\Scripts\python.exe scripts\run_demo.py --once --speed 1000"



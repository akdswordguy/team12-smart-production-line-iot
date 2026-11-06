$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    # Prefer Python 3.12: pinned packages such as PyYAML 6.0.2 have no wheels for newer Pythons.
    $made = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { & py -3.12 -m venv .venv; $made = ($LASTEXITCODE -eq 0) } catch {}
        if (-not $made) { & py -3 -m venv .venv; $made = ($LASTEXITCODE -eq 0) }
    }
    if (-not $made) { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw "Could not create Python virtual environment" }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Python package installation failed" }
Write-Host "Device laptop ready. Set HiveMQ environment variables, then run scripts\two_laptop.py device."

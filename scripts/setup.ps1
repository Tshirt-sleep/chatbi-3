$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root
$env:CHATBI_DATABASE_URL = "sqlite:///data/local/chatbi.sqlite"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11 is required. Install Python, then run this script again."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js and npm are required. Install Node.js 20.19 or newer, then run this script again."
}
$pythonVersion = [version](python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
if ($pythonVersion.Major -ne 3 -or $pythonVersion.Minor -lt 11 -or $pythonVersion.Minor -ge 13) {
    throw "Python 3.11 or 3.12 is required; found $pythonVersion."
}
$nodeVersionText = (node --version).TrimStart("v")
$nodeVersion = [version]$nodeVersionText
if ($nodeVersion -lt [version]"20.19.0") {
    throw "Node.js 20.19 or newer is required; found $nodeVersion."
}

$env:PIP_CACHE_DIR = Join-Path $root ".pip-cache"
$pythonPath = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
}
& $pythonPath -m pip install -r backend\requirements-dev.lock
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

npm --prefix frontend ci --cache (Join-Path $root ".npm-cache")
if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }

& $pythonPath scripts\generate_mock_data.py
if ($LASTEXITCODE -ne 0) { throw "Mock dataset generation failed." }
& $pythonPath scripts\generate_saas_mock_data.py
if ($LASTEXITCODE -ne 0) { throw "SaaS Mock dataset generation failed." }

New-Item -ItemType Directory -Force -Path data\local | Out-Null
& $pythonPath -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
& $pythonPath -m backend.chatbi.seed --reset
if ($LASTEXITCODE -ne 0) { throw "Local Mock database seeding failed." }

Write-Host "Setup complete. Run 'npm run dev' from the project root."

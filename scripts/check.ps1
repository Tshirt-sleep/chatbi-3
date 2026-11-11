$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root
$pythonPath = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Run .\scripts\setup.ps1 first." }

& $pythonPath -m ruff format --check backend harness
if ($LASTEXITCODE -ne 0) { throw "Python formatting check failed." }
& $pythonPath -m ruff check backend harness
if ($LASTEXITCODE -ne 0) { throw "Python lint check failed." }
& $pythonPath -m mypy --config-file backend\pyproject.toml backend\chatbi
if ($LASTEXITCODE -ne 0) { throw "Python type check failed." }
& $pythonPath -m pytest
if ($LASTEXITCODE -ne 0) { throw "Python checks failed." }
npm --prefix frontend run typecheck
if ($LASTEXITCODE -ne 0) { throw "Frontend type check failed." }
npm --prefix frontend run test:result-table
if ($LASTEXITCODE -ne 0) { throw "Frontend result table checks failed." }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }

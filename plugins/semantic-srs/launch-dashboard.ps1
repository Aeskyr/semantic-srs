$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'SemanticSRS'
$python = Join-Path $root 'venvs\semantic-srs\Scripts\python.exe'
$app = Join-Path $root 'apps\current\semantic-srs'
$env:SEMANTIC_SRS_DATA_DIR = Join-Path $root 'data'
if (-not (Test-Path -LiteralPath $python)) { throw "Semantic SRS runtime is missing. Run setup.ps1." }
Push-Location $app
try { & $python (Join-Path $app 'launch_dashboard.py') } finally { Pop-Location }

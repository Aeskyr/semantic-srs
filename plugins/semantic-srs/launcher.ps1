$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'SemanticSRS'
$python = Join-Path $root 'venvs\semantic-srs\Scripts\python.exe'
$server = Join-Path $root 'apps\current\semantic-srs\server.py'
$env:SEMANTIC_SRS_DATA_DIR = Join-Path $root 'data'
if (-not (Test-Path -LiteralPath $python)) { throw "Semantic SRS runtime is missing. Run setup.ps1." }
& $python $server
exit $LASTEXITCODE

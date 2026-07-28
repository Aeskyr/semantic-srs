$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'SemanticSRS'
$python = Join-Path $root 'venvs\local-rag\Scripts\python.exe'
$server = Join-Path $root 'apps\current\local-rag\server.py'
$env:LOCAL_RAG_DATA_DIR = Join-Path $root 'rag\qdrant'
$env:LOCAL_RAG_MODEL_DIR = Join-Path $root 'rag\models'
if (-not (Test-Path -LiteralPath $python)) { throw "Local RAG runtime is missing. Run setup.ps1 without -SkipLocalRag." }
& $python $server
exit $LASTEXITCODE

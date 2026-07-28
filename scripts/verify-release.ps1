$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$semanticPython = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $semanticPython)) { $semanticPython = 'python' }

Push-Location (Join-Path $repo 'plugins\semantic-srs')
try {
    & $semanticPython '.\scripts\check_docs.py'
    if ($LASTEXITCODE -ne 0) { throw 'Documentation validation failed.' }
    & $semanticPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Semantic SRS tests failed.' }
} finally { Pop-Location }

& $semanticPython (Join-Path $repo 'scripts\validate_release.py')
if ($LASTEXITCODE -ne 0) { throw 'Release validation failed.' }
& $semanticPython -m unittest discover -s (Join-Path $repo 'tests') -v
if ($LASTEXITCODE -ne 0) { throw 'Installer tests failed.' }

$ragPython = Join-Path $repo '..\local-rag\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $ragPython)) { $ragPython = $semanticPython }
Push-Location (Join-Path $repo 'plugins\local-rag')
try {
    & $ragPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Local RAG tests failed.' }
} finally { Pop-Location }

Write-Host 'All available release checks passed.'

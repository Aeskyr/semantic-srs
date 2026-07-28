[CmdletBinding()]
param(
    [Alias('Host')][ValidateSet('Codex','Claude','Both')][string]$TargetHost,
    [switch]$SkipLocalRag,
    [switch]$NonInteractive,
    [switch]$MigrateLegacy,
    [switch]$SkipHostRegistration,
    [switch]$SkipDependencies,
    [string]$Python = 'py'
)

$ErrorActionPreference = 'Stop'
$script:Version = '0.2.1'
$script:Repo = $PSScriptRoot
$script:InstallRoot = Join-Path $env:LOCALAPPDATA 'SemanticSRS'

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Resolve-Hosts {
    if ($TargetHost) { return $TargetHost }
    $hasCodex = Test-Command 'codex'
    $hasClaude = Test-Command 'claude'
    if (-not $hasCodex -and -not $hasClaude) {
        throw 'Neither Codex nor Claude Code was detected. Install a host or pass -SkipHostRegistration for runtime-only setup.'
    }
    $recommended = if ($hasCodex -and $hasClaude) {'Both'} elseif ($hasCodex) {'Codex'} else {'Claude'}
    if ($NonInteractive) { return $recommended }
    $answer = Read-Host "Install for Codex, Claude, or Both? [$recommended]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $recommended }
    if ($answer -notin @('Codex','Claude','Both')) { throw "Invalid host: $answer" }
    return $answer
}

function Invoke-Python([string[]]$Arguments) {
    if ($Python -eq 'py') { & py -3.11 @Arguments } else { & $Python @Arguments }
    if ($LASTEXITCODE -ne 0) { throw "Python failed with exit code $LASTEXITCODE." }
}

function Install-App([string]$Name) {
    $source = Join-Path $script:Repo "plugins\$Name"
    $versions = Join-Path $script:InstallRoot "apps\versions\$script:Version"
    $target = Join-Path $versions $Name
    $temp = "$target.new"
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    Copy-Item -Path (Join-Path $source '*') -Destination $temp -Recurse -Force
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    Move-Item -LiteralPath $temp -Destination $target
}

function Install-Environment([string]$Name) {
    if ($SkipDependencies) { return }
    $lock = Join-Path $script:Repo "plugins\$Name\requirements.txt"
    $venv = Join-Path $script:InstallRoot "venvs\$Name"
    $marker = Join-Path $venv '.requirements.sha256'
    $hash = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash
    $oldHash = if (Test-Path -LiteralPath $marker) {(Get-Content -LiteralPath $marker -Raw).Trim()} else {''}
    if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
        Invoke-Python @('-m','venv',$venv)
        $oldHash = ''
    }
    if ($oldHash -ne $hash) {
        & (Join-Path $venv 'Scripts\python.exe') -m pip install --disable-pip-version-check -r $lock
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed for $Name." }
        Set-Content -LiteralPath $marker -Value $hash -Encoding ascii
    }
}

function Set-CurrentApps([string[]]$Names) {
    $current = Join-Path $script:InstallRoot 'apps\current'
    $temp = Join-Path $script:InstallRoot 'apps\current.new'
    $old = Join-Path $script:InstallRoot 'apps\current.old'
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    foreach ($name in $Names) {
        Copy-Item -LiteralPath (Join-Path $script:InstallRoot "apps\versions\$script:Version\$name") -Destination (Join-Path $temp $name) -Recurse
    }
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
    if (Test-Path -LiteralPath $current) { Move-Item -LiteralPath $current -Destination $old }
    Move-Item -LiteralPath $temp -Destination $current
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
}

function Copy-LegacyStore([string]$Source, [string]$Destination, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Source)) { return }
    $sourceFiles = @(Get-ChildItem -LiteralPath $Source -File -Recurse -ErrorAction SilentlyContinue)
    $destinationFiles = @(Get-ChildItem -LiteralPath $Destination -File -Recurse -ErrorAction SilentlyContinue)
    if ($sourceFiles.Count -eq 0) { return }
    if ($destinationFiles.Count -gt 0) {
        if ($MigrateLegacy) {
            throw "Refusing to merge nonempty $Label stores. Back up and choose one store manually."
        }
        return
    }
    if (-not $MigrateLegacy -and $NonInteractive) { return }
    if (-not $MigrateLegacy) {
        $answer = Read-Host "Migrate legacy $Label data from '$Source'? [Y/n]"
        if ($answer -match '^(n|no)$') { return }
    }
    Copy-Item -Path (Join-Path $Source '*') -Destination $Destination -Recurse -Force
}

function Register-Plugins([string]$SelectedHost, [string[]]$Names) {
    if ($SkipHostRegistration) { return }
    $targets = if ($SelectedHost -eq 'Both') {@('Codex','Claude')} else {@($SelectedHost)}
    foreach ($targetHost in $targets) {
        $exe = $targetHost.ToLowerInvariant()
        if (-not (Test-Command $exe)) { throw "$targetHost CLI was requested but is not installed." }
        & $exe plugin marketplace add 'https://github.com/Aeskyr/semantic-srs'
        if ($LASTEXITCODE -ne 0) { throw "$targetHost marketplace registration failed." }
        foreach ($name in $Names) {
            if ($targetHost -eq 'Codex') {
                & $exe plugin add "$name@semantic-srs"
            } else {
                & $exe plugin install "$name@semantic-srs"
            }
            if ($LASTEXITCODE -ne 0) { throw "$targetHost plugin installation failed for $name." }
        }
    }
}

$selectedHost = if ($SkipHostRegistration -and -not $TargetHost) {'Codex'} else {Resolve-Hosts}
$names = @('semantic-srs')
if (-not $SkipLocalRag) { $names += 'local-rag' }

foreach ($path in @('apps\versions','venvs','data','rag\qdrant','rag\models','backups','logs')) {
    New-Item -ItemType Directory -Path (Join-Path $script:InstallRoot $path) -Force | Out-Null
}

$legacySrs = Join-Path $script:Repo 'data'
$legacyRag = Join-Path $env:USERPROFILE 'local-rag-data'
Copy-LegacyStore $legacySrs (Join-Path $script:InstallRoot 'data') 'Semantic SRS'
if (-not $SkipLocalRag) { Copy-LegacyStore $legacyRag (Join-Path $script:InstallRoot 'rag') 'Local RAG' }

foreach ($name in $names) {
    Install-App $name
    Install-Environment $name
}
Set-CurrentApps $names
Register-Plugins $selectedHost $names

@{
    version = $script:Version
    host = $selectedHost
    local_rag = -not $SkipLocalRag
    repository = $script:Repo
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $script:InstallRoot 'install.json') -Encoding utf8

Write-Host "Semantic SRS $script:Version is installed for $selectedHost."
if (-not $SkipLocalRag) { Write-Host 'Local RAG is installed. Its embedding model downloads once on first use; retrieval is local afterward.' }

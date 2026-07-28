[CmdletBinding(SupportsShouldProcess)]
param(
    [Alias('Host')][ValidateSet('Codex','Claude','Both')][string]$TargetHost = 'Both',
    [switch]$PurgeData,
    [switch]$SkipHostRegistration
)

$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'SemanticSRS'
if (-not $SkipHostRegistration) {
    $targets = if ($TargetHost -eq 'Both') {@('codex','claude')} else {@($TargetHost.ToLowerInvariant())}
    foreach ($exe in $targets) {
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            foreach ($name in @('semantic-srs','local-rag')) { & $exe plugin uninstall "$name@semantic-srs" 2>$null }
            & $exe plugin marketplace remove 'semantic-srs' 2>$null
        }
    }
}

foreach ($relative in @('apps','venvs','logs','install.json')) {
    $target = Join-Path $root $relative
    if ((Test-Path -LiteralPath $target) -and $PSCmdlet.ShouldProcess($target, 'Remove runtime')) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
if ($PurgeData) {
    foreach ($relative in @('data','rag','backups')) {
        $target = Join-Path $root $relative
        if ((Test-Path -LiteralPath $target) -and $PSCmdlet.ShouldProcess($target, 'Permanently remove learner data')) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
    Write-Host 'Runtime and learner data were permanently removed.'
} else {
    Write-Host "Runtime removed. Learner data is preserved under $root."
}

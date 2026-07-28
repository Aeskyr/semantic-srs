[CmdletBinding()]
param(
    [Alias('Host')][ValidateSet('Codex','Claude','Both')][string]$TargetHost,
    [switch]$SkipLocalRag,
    [switch]$NonInteractive,
    [switch]$SkipHostRegistration,
    [string]$Python = 'py'
)

$ErrorActionPreference = 'Stop'
$argsForSetup = @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'setup.ps1'),'-NonInteractive')
if ($TargetHost) { $argsForSetup += @('-Host',$TargetHost) }
if ($SkipLocalRag) { $argsForSetup += '-SkipLocalRag' }
if ($SkipHostRegistration) { $argsForSetup += '-SkipHostRegistration' }
if ($Python -ne 'py') { $argsForSetup += @('-Python',$Python) }
& powershell.exe @argsForSetup
exit $LASTEXITCODE

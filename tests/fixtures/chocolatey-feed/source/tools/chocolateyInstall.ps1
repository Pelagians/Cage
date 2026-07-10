$ErrorActionPreference = 'Stop'

$helperModule = Join-Path $env:ChocolateyInstall 'helpers\chocolateyInstaller.psm1'
if (-not (Test-Path -LiteralPath $helperModule -PathType Leaf)) {
    throw "Required Chocolatey helper module is missing: $helperModule"
}
Import-Module $helperModule -Force
$toolsLocation = Get-ToolsLocation
if ([string]::IsNullOrWhiteSpace($toolsLocation)) {
    throw 'Get-ToolsLocation did not return a usable path'
}

$runId = $env:CAGE_CHOCOLATEY_SMOKE_RUN_ID
if ([string]::IsNullOrWhiteSpace($runId)) {
    throw 'CAGE_CHOCOLATEY_SMOKE_RUN_ID is required'
}
$evidenceRoot = Join-Path $env:ProgramData 'Cage'
$sentinel = Join-Path $evidenceRoot 'chocolatey-smoke.sentinel'
$evidencePath = Join-Path $evidenceRoot 'chocolatey-smoke-install.json'
New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null
New-Item -ItemType File -Path $sentinel -Force | Out-Null
[Environment]::SetEnvironmentVariable('CAGE_CHOCOLATEY_SMOKE', $runId, 'User')

$process = Get-Process -Id $PID
$evidence = [ordered]@{
    schemaVersion = 'cage.chocolatey-smoke-install/v0'
    RunId = $runId
    helperModule = $helperModule
    helperCommand = 'Get-ToolsLocation'
    toolsLocation = $toolsLocation
    PSVersion = $PSVersionTable.PSVersion.ToString()
    PSEdition = $PSVersionTable.PSEdition
    ProcessPath = $process.Path
    ProcessId = $PID
    Is64BitProcess = [Environment]::Is64BitProcess
    ChocolateyInstall = $env:ChocolateyInstall
    ChocolateyToolsLocation = $env:ChocolateyToolsLocation
    sentinel = $sentinel
}
$evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $evidencePath -Encoding UTF8

if (-not (Test-Path -LiteralPath $sentinel -PathType Leaf)) {
    throw "Smoke sentinel was not created: $sentinel"
}
if ([Environment]::GetEnvironmentVariable('CAGE_CHOCOLATEY_SMOKE', 'User') -ne $runId) {
    throw 'Smoke environment marker was not persisted'
}

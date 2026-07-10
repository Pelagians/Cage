$ErrorActionPreference = 'Stop'

$runId = $env:CAGE_CHOCOLATEY_SMOKE_RUN_ID
if ([string]::IsNullOrWhiteSpace($runId)) {
    throw 'CAGE_CHOCOLATEY_SMOKE_RUN_ID is required during uninstall'
}
$evidenceRoot = Join-Path $env:ProgramData 'Cage'
$sentinel = Join-Path $evidenceRoot 'chocolatey-smoke.sentinel'
$proofPath = Join-Path $evidenceRoot 'chocolatey-smoke-uninstall-proof.json'
Remove-Item -LiteralPath $sentinel -Force -ErrorAction SilentlyContinue
[Environment]::SetEnvironmentVariable('CAGE_CHOCOLATEY_SMOKE', $null, 'User')

$process = Get-Process -Id $PID
$proof = [ordered]@{
    schemaVersion = 'cage.chocolatey-smoke-uninstall/v0'
    RunId = $runId
    PSVersion = $PSVersionTable.PSVersion.ToString()
    ProcessPath = $process.Path
    ProcessId = $PID
    Is64BitProcess = [Environment]::Is64BitProcess
    sentinelRemoved = -not (Test-Path -LiteralPath $sentinel)
    markerRemoved = [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('CAGE_CHOCOLATEY_SMOKE', 'User'))
}
$proof | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $proofPath -Encoding UTF8

if (Test-Path -LiteralPath $sentinel) {
    throw "Smoke sentinel still exists after uninstall: $sentinel"
}
if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('CAGE_CHOCOLATEY_SMOKE', 'User'))) {
    throw 'Smoke environment marker still exists after uninstall'
}

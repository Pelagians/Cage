# Chocolatey profile integration for an orchestrator-owned profile loader.
# Source: noahgiroux/Chocolatey-for-wine compat contract, commit c3b4923d0f63188843bd2a15be64bca8f4a9902b.

$chocolateyRoot = if ($env:ChocolateyInstall) {
    $env:ChocolateyInstall
}
else {
    Join-Path $env:ProgramData 'chocolatey'
}

$chocolateyProfile = Join-Path $chocolateyRoot 'helpers\chocolateyProfile.psm1'
if (Test-Path -LiteralPath $chocolateyProfile -PathType Leaf) {
    Import-Module -Name $chocolateyProfile -Force -ErrorAction Stop
}

Remove-Variable chocolateyRoot, chocolateyProfile -ErrorAction SilentlyContinue

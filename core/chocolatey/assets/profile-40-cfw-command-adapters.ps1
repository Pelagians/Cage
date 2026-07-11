# Load optional Chocolatey-for-Wine command adapters without replacing the
# Cage-owned PowerShell profile or Synchro wrapper layer.
# Source: noahgiroux/Chocolatey-for-wine compat contract, commit c3b4923d0f63188843bd2a15be64bca8f4a9902b.

$adapterRoot = Join-Path $env:ProgramData 'Chocolatey-for-wine\command-adapters'
if (Test-Path -LiteralPath $adapterRoot -PathType Container) {
    Get-ChildItem -LiteralPath $adapterRoot -Filter '*.ps1' -File |
        Sort-Object -Property Name |
        ForEach-Object {
            . $_.FullName
        }
}

Remove-Variable adapterRoot -ErrorAction SilentlyContinue

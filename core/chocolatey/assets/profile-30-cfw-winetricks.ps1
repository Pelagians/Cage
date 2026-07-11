# Optional Chocolatey-for-Wine winetricks entrypoint.
# Source: noahgiroux/Chocolatey-for-wine compat contract, commit c3b4923d0f63188843bd2a15be64bca8f4a9902b.

function Invoke-CfwWinetricks {
    [CmdletBinding()]
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [object[]] $ArgumentList
    )

    $scriptPath = Join-Path $env:ProgramData 'Chocolatey-for-wine\winetricks.ps1'
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Chocolatey-for-Wine winetricks script is missing: $scriptPath"
    }

    & $scriptPath @ArgumentList
}

Set-Alias -Name winetricks -Value Invoke-CfwWinetricks -Scope Global -Force

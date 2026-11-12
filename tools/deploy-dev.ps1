# Links extension\PixelsFGU into the FGU extensions folder (directory junction),
# so edits are picked up on the next campaign load / /reload without copying.
param(
    [string]$DataDir = (Get-ItemProperty "HKCU:\Software\SmiteWorks\Fantasy Grounds" -Name DataDir).DataDir
)
$src = Join-Path $PSScriptRoot "..\extension\PixelsFGU" | Resolve-Path
$dst = Join-Path $DataDir "extensions\PixelsFGU"
if (Test-Path $dst) {
    $item = Get-Item $dst -Force
    if ($item.LinkType -eq "Junction") { Write-Host "Already linked: $dst -> $($item.Target)"; exit 0 }
    throw "$dst exists and is not a junction; remove it first."
}
New-Item -ItemType Junction -Path $dst -Target $src | Out-Null
Write-Host "Linked $dst -> $src"

<#
.SYNOPSIS
    Launches the Film Demo Director: a repeatable, mostly-Space/Continue-driven
    recording of Continuity AI's real Live Project flow (real Codex Source
    Scoping, mandatory manual approval, real report, real Evidence Inspector).

.DESCRIPTION
    This script only prepares the environment and starts the existing
    `npm run tauri dev` desktop app with the Film Demo Director flag set. It
    never talks to the Bridge itself and never fakes a result: every shot in
    the recording is produced by the same `continuitySession` Bridge commands
    the manual Live Project flow already uses.

.PARAMETER ArtifactRoot
    Path to a synthetic Project Aurora artifact folder to load without a file
    dialog. If omitted, one is generated fresh via the existing
    `continuity-ai generate-aurora-fixture` CLI command into a temp folder.

.PARAMETER VaultPath
    Path for a brand-new, empty demo vault. Must not already exist. If
    omitted, a fresh path is generated under the system temp folder.

.PARAMETER OwnerName
    Display name recorded as the vault owner for this run.

.PARAMETER Question
    The report question submitted for the real report shot.

.EXAMPLE
    ./scripts/run_film_demo.ps1

    Generates a synthetic Aurora fixture and a clean temp vault automatically,
    then opens the desktop app straight into the Film Demo Director.
#>

param(
    [string]$ArtifactRoot,
    [string]$VaultPath,
    [string]$OwnerName = "Demo Owner",
    [string]$Question = "What is the current project state?"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DesktopRoot = Join-Path $RepoRoot "desktop"

if (-not (Test-Path (Join-Path $DesktopRoot "package.json"))) {
    throw "Could not find desktop/package.json under $RepoRoot. Run this script from the Continuity AI repository."
}

$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$DemoTempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "continuity-film-demo-$RunStamp"
New-Item -ItemType Directory -Force -Path $DemoTempRoot | Out-Null

if (-not $ArtifactRoot) {
    $ArtifactRoot = Join-Path $DemoTempRoot "project-aurora"
    Write-Host "No -ArtifactRoot given: generating a synthetic Project Aurora fixture at $ArtifactRoot"
    Push-Location $RepoRoot
    try {
        uv run continuity-ai generate-aurora-fixture --output-root $ArtifactRoot | Out-Null
    } finally {
        Pop-Location
    }
} elseif (-not (Test-Path $ArtifactRoot)) {
    throw "-ArtifactRoot '$ArtifactRoot' does not exist."
}

if (-not $VaultPath) {
    $VaultPath = Join-Path $DemoTempRoot "demo-vault"
} elseif (Test-Path $VaultPath) {
    throw "-VaultPath '$VaultPath' already exists. The demo always creates a brand-new, empty vault."
}

# Generated once per run and never displayed anywhere, including the
# director panel and this script's own output.
$PasswordBytes = New-Object byte[] 24
[System.Security.Cryptography.RandomNumberGenerator]::Fill($PasswordBytes)
$DemoPassword = [Convert]::ToBase64String($PasswordBytes)

$env:CONTINUITY_FILM_DEMO = "1"
$env:CONTINUITY_BACKEND_ROOT = $RepoRoot.Path
if (-not $env:CONTINUITY_REASONING_PROVIDER) {
    $env:CONTINUITY_REASONING_PROVIDER = "deterministic_offline"
}

$env:VITE_CONTINUITY_FILM_DEMO = "1"
$env:VITE_CONTINUITY_FILM_DEMO_ARTIFACT_ROOT = $ArtifactRoot
$env:VITE_CONTINUITY_FILM_DEMO_VAULT_PATH = $VaultPath
$env:VITE_CONTINUITY_FILM_DEMO_OWNER_NAME = $OwnerName
$env:VITE_CONTINUITY_FILM_DEMO_QUESTION = $Question
$env:VITE_CONTINUITY_FILM_DEMO_PASSWORD = $DemoPassword

Write-Host ""
Write-Host "Film Demo Director starting."
Write-Host "  Artifact root: $ArtifactRoot"
Write-Host "  Vault path:    $VaultPath"
Write-Host "  Owner name:    $OwnerName"
Write-Host "  Question:      $Question"
Write-Host "  Reasoning provider: $($env:CONTINUITY_REASONING_PROVIDER)"
Write-Host ""
Write-Host "In the app: Space or Continue advances each shot. Shot 6 (manual"
Write-Host "approval) requires an explicit click on the real approval button"
Write-Host "and will never advance on its own."
Write-Host ""

Push-Location $DesktopRoot
try {
    npm run tauri dev
} finally {
    Pop-Location
}

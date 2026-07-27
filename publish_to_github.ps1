param(
    [string]$RepositoryName = "cyprus-weather-limassol-tepak",
    [ValidateSet("private", "public")]
    [string]$Visibility = "private"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is not installed or is not available in PATH."
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "GitHub CLI (gh) is not installed."
    Write-Host "Install it with:"
    Write-Host "  winget install --id GitHub.cli"
    Write-Host ""
    Write-Host "Then reopen VS Code and run:"
    Write-Host "  gh auth login"
    Write-Host "  .\publish_to_github.ps1"
    exit 1
}

gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    gh auth login
}

if (-not (Test-Path ".git")) {
    git init
}

git add .
git commit -m "Initial LIMASSOL and TEPAK weather collector"
if ($LASTEXITCODE -ne 0) {
    Write-Host "No new local changes needed for the initial commit."
}

git branch -M main

$existingRemote = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $existingRemote) {
    Write-Host "Using existing origin: $existingRemote"
    git push -u origin main
} else {
    gh repo create $RepositoryName "--$Visibility" --source=. --remote=origin --push
}

Write-Host ""
Write-Host "Repository published."
Write-Host "Open the repository's Actions tab and run 'Collect Cyprus weather' once."

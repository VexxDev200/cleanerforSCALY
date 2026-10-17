# Один раз: логин GitHub + репо + релиз v1.0.0 (exe уже в dist после publish_all.bat)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$gh = "C:\Program Files\GitHub CLI\gh.exe"
if (-not (Test-Path $gh)) { $gh = "gh" }

& $gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Откроется вход GitHub (браузер)..."
    & $gh auth login -h github.com -p https -w
}

if (-not (Test-Path ".git")) {
    git init -b main
    git add -A
    git commit -m "SCALY Cleaner initial release"
}

$settings = Get-Content "release_settings.json" -Raw | ConvertFrom-Json
$repo = "$($settings.github_user)/$($settings.github_repo)"

$remotes = git remote 2>$null
if ($remotes -notcontains "origin") {
    & $gh repo create $settings.github_repo --public --source=. --remote=origin --description "SCALY Cleaner"
    git push -u origin main
} else {
    git push -u origin main
}

$ver = (Select-String -Path "scalyclean\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches.Groups[1].Value
$tag = "v$ver"
$exe = "dist\ScalyCleaner.exe"
if (-not (Test-Path $exe)) {
    python tools\build_release.py
}

$notes = $settings.release_notes
& $gh release create $tag -R $repo --title "SCALY Cleaner $tag" --notes $notes $exe "dist\ScalyCleaner-v$ver-win64.zip"
Write-Host "Done: https://github.com/$repo/releases/tag/$tag"
Write-Host "Users with exe will get updates from releases/version.json on main."

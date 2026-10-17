# Push manifest + GitHub release (run after .\publish_all.bat)
Set-Location $PSScriptRoot\..

$gh = "C:\Program Files\GitHub CLI\gh.exe"
if (-not (Test-Path $gh)) { $gh = "gh" }

function Test-GhAuth {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & $gh auth status *> $null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $old
    return $ok
}

if (-not (Test-GhAuth)) {
    Write-Host "GitHub login required."
    & $gh auth login -h github.com -p https -w
    if (-not (Test-GhAuth)) { exit 1 }
}

$ver = (Select-String -Path "scalyclean\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches.Groups[1].Value
$manifestPath = "releases\version.json"
if (-not (Test-Path $manifestPath)) {
    Write-Host "Missing releases\version.json — run .\publish_all.bat"
    exit 1
}
$manifestVer = (Get-Content $manifestPath -Raw | ConvertFrom-Json).version
if ($manifestVer -ne $ver) {
    Write-Host "Version mismatch: code v$ver but manifest v$manifestVer"
    Write-Host "Run .\publish_all.bat from project root (not old commit)."
    exit 1
}

git add releases/version.json scalyclean/__init__.py
git diff --staged --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "release manifest v$ver"
}
git push origin main
if ($LASTEXITCODE -ne 0) { exit 1 }

$settings = Get-Content "release_settings.json" -Raw | ConvertFrom-Json
$repo = "$($settings.github_user)/$($settings.github_repo)"
$tag = "v$ver"
$exe = "dist\ScalyCleaner.exe"
$zip = "dist\ScalyCleaner-v$ver-win64.zip"

if (-not (Test-Path $exe)) {
    Write-Host "Missing dist\ScalyCleaner.exe — run .\publish_all.bat"
    exit 1
}

$upload = @($exe)
if (Test-Path $zip) { $upload += $zip }

$old = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
& $gh release view $tag -R $repo *> $null
$releaseExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $old

$notes = $settings.release_notes
if ($releaseExists) {
    & $gh release upload $tag -R $repo --clobber @upload
} else {
    & $gh release create $tag -R $repo --title "SCALY Cleaner $tag" --notes $notes @upload
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done: https://github.com/$repo/releases/tag/$tag"
Start-Sleep -Seconds 2
python tools\verify_auto_update.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "If manifest still old, wait 30s and run: python tools\verify_auto_update.py"
    exit $LASTEXITCODE
}

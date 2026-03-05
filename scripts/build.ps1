param(
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($InstallDeps) {
    py -m pip install --upgrade pyinstaller
}

$IconPath = Join-Path $ProjectRoot "assets\screen-reader.ico"
$Entry = Join-Path $ProjectRoot "src\screen_reader\__main__.py"
$DistPath = Join-Path $ProjectRoot "dist"
$BuildPath = Join-Path $env:TEMP "screen-reader-pyinstaller-build"

if (Test-Path $BuildPath) {
  Remove-Item -Recurse -Force $BuildPath -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $BuildPath | Out-Null

py -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name "screen-reader" `
  --icon "$IconPath" `
  --distpath "$DistPath" `
  --workpath "$BuildPath" `
  "$Entry"

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

& "$DistPath\screen-reader.exe" --help | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "Smoke check failed: screen-reader.exe --help"
}

Write-Host "Build complete: $DistPath\\screen-reader.exe"

param(
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($InstallDeps) {
    py -m pip install --upgrade pyinstaller
}

$IconPath = Join-Path $ProjectRoot "assets\snapnarrate.ico"
$Entry = Join-Path $ProjectRoot "src\snap_narrate\__main__.py"
$DistPath = Join-Path $ProjectRoot "dist"
$BuildPath = Join-Path $env:TEMP "snapnarrate-pyinstaller-build"
$ExePath = Join-Path $DistPath "snapnarrate.exe"

if (Test-Path $BuildPath) {
  Remove-Item -Recurse -Force $BuildPath -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $BuildPath | Out-Null
New-Item -ItemType Directory -Force -Path $DistPath | Out-Null

# Stop any running snapnarrate process to avoid file lock on dist\snapnarrate.exe
Get-Process | Where-Object { $_.ProcessName -eq "snapnarrate" } | ForEach-Object {
  try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch {}
}

# Best-effort cleanup of previous executable with short retry window.
if (Test-Path $ExePath) {
  for ($i = 0; $i -lt 5; $i++) {
    try {
      Remove-Item -Force $ExePath -ErrorAction Stop
      break
    } catch {
      Start-Sleep -Milliseconds 400
    }
  }
}

py -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name "snapnarrate" `
  --icon "$IconPath" `
  --distpath "$DistPath" `
  --workpath "$BuildPath" `
  "$Entry"

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

& "$DistPath\snapnarrate.exe" --help | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "Smoke check failed: snapnarrate.exe --help"
}

Write-Host "Build complete: $DistPath\\snapnarrate.exe"



<#
.SYNOPSIS
  Build SnapNarrate: tests, PyInstaller app folder, and (if Inno Setup 6 is installed) the installer.

.DESCRIPTION
  Uses an isolated .venv-build with pinned versions from packaging/requirements-build.txt,
  so a build depends only on the commit, not on whatever is in your global Python.

  Output (in -OutDir; defaults to .\dist, or %LOCALAPPDATA%\SnapNarrate-build when the
  project lives in OneDrive, whose sync locks build folders and would upload ~80 MB per build):
    SnapNarrate\SnapNarrate.exe            tray app (windowed)
    SnapNarrate\snapnarrate-cli.exe        command line (doctor, voices, usage, ...)
    installer\SnapNarrate-Setup-X.Y.Z.exe  installer (needs Inno Setup 6: https://jrsoftware.org/isinfo.php)

.EXAMPLE
  .\scripts\build.ps1
  .\scripts\build.ps1 -SkipTests -SkipInstaller
#>
param(
  [string]$OutDir,
  [switch]$SkipTests,
  [switch]$SkipInstaller,
  [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked([string]$What, [scriptblock]$Command) {
  # Native tools (pip, PyInstaller) log to stderr; Windows PowerShell 5.1 would turn that into
  # a terminating error under "Stop". Judge success by exit code instead.
  $previous = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { & $Command } finally { $ErrorActionPreference = $previous }
  if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

if (-not $OutDir) {
  $inOneDrive = $env:OneDrive -and $Root.StartsWith($env:OneDrive, [StringComparison]::OrdinalIgnoreCase)
  $OutDir = if ($inOneDrive) { Join-Path $env:LOCALAPPDATA "SnapNarrate-build" } else { Join-Path $Root "dist" }
}
$OutDir = [IO.Path]::GetFullPath($OutDir)

$Venv = Join-Path $Root ".venv-build"
if ($Clean -and (Test-Path $Venv)) { Remove-Item -Recurse -Force $Venv }
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
  Write-Host "Creating build environment..."
  Invoke-Checked "venv" { py -3 -m venv $Venv }
}
$Py = "$Venv\Scripts\python.exe"

Write-Host "Installing pinned build dependencies..."
Invoke-Checked "pip install" { & $Py -m pip install --quiet --disable-pip-version-check -r packaging\requirements-build.txt }
Invoke-Checked "pip install snapnarrate" { & $Py -m pip install --quiet --disable-pip-version-check --no-deps -e . }

$Version = (& $Py -c "import snap_narrate; print(snap_narrate.__version__)").Trim()
Write-Host "Building SnapNarrate $Version"

if (-not $SkipTests) {
  Invoke-Checked "tests" { & $Py -m pytest -q }
}

# A running copy locks files in the output folder.
Get-Process -Name "SnapNarrate", "snapnarrate-cli" -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -and $_.Path.StartsWith($OutDir, [StringComparison]::OrdinalIgnoreCase) } |
  Stop-Process -Force

# Work files go to %TEMP%: inside a OneDrive folder, sync locks them and --clean fails with "Access is denied".
$WorkPath = Join-Path $env:TEMP "snapnarrate-pyinstaller"
Invoke-Checked "PyInstaller" {
  & $Py -m PyInstaller --noconfirm --clean --distpath $OutDir --workpath $WorkPath packaging\snapnarrate.spec
}

$AppDir = Join-Path $OutDir "SnapNarrate"
$Cli = Join-Path $AppDir "snapnarrate-cli.exe"
$Reported = (& $Cli --version).Trim()
if ($LASTEXITCODE -ne 0 -or $Reported -ne "SnapNarrate $Version") {
  throw "Smoke check failed: '$Cli --version' printed '$Reported'"
}
Write-Host "App folder: $AppDir ($Reported)"

if ($SkipInstaller) { return }

$Iscc = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $Iscc) {
  Write-Warning "Inno Setup 6 not found; skipped the installer. Install it (winget install JRSoftware.InnoSetup) and re-run."
  return
}
$InstallerDir = Join-Path $OutDir "installer"
Invoke-Checked "Inno Setup" {
  & $Iscc /Q "/DAppVersion=$Version" "/DSourceDir=$AppDir" "/DOutputDir=$InstallerDir" packaging\installer.iss
}
Write-Host "Installer: $InstallerDir\SnapNarrate-Setup-$Version.exe"

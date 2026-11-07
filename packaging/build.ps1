<#
.SYNOPSIS
  Builds MXB for Windows: dist\MXB\MXB.exe (PyInstaller) and dist\MXB-Setup-<version>.exe (Inno Setup).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipInstaller
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -NoVenv      # CI: use the current Python

.NOTES
  Needs Python 3.11+ and, for the installer, Inno Setup 6.3+ (winget install JRSoftware.InnoSetup).
  Builds inside .build-venv so the bundle contains only what MXB needs, then runs the frozen
  exe's --smoke-test and refuses to make an installer if any module or data file is missing.
#>
param(
  [string]$Python = "python",
  [switch]$NoVenv,
  [switch]$Clean,
  [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

$version = (& $Python -c "from utils.version import __version__; print(__version__)").Trim()
Check "Reading utils/version.py"
$numeric = $version -replace '[^0-9.].*$', ''
Step "Building MXB $version"

# 1. Build environment ---------------------------------------------------------------------
if ($NoVenv) {
  $py = $Python
} else {
  $venv = Join-Path $Root ".build-venv"
  if ($Clean -and (Test-Path $venv)) { Remove-Item -Recurse -Force $venv }
  if (-not (Test-Path $venv)) {
    Step "Creating build venv"
    & $Python -m venv $venv; Check "venv"
  }
  $py = Join-Path $venv "Scripts\python.exe"
}
Step "Installing dependencies"
& $py -m pip install --upgrade pip --quiet; Check "pip upgrade"
& $py -m pip install -r requirements.txt -r requirements-build.txt --quiet; Check "pip install"

# 2. Icon -----------------------------------------------------------------------------------
Step "Drawing icon"
& $py packaging\make_icon.py packaging\mxb.ico; Check "make_icon"

# 3. PyInstaller ----------------------------------------------------------------------------
Step "Freezing with PyInstaller"
if (Test-Path dist\MXB) { Remove-Item -Recurse -Force dist\MXB }
& $py -m PyInstaller packaging\mxb.spec --noconfirm --clean --distpath dist --workpath build; Check "PyInstaller"
if (-not (Test-Path dist\MXB\MXB.exe)) { throw "dist\MXB\MXB.exe was not produced" }

# 4. Smoke test the frozen exe (it has no console, so it reports through a JSON file) ---------
Step "Smoke-testing the frozen build"
$report = Join-Path $Root "dist\smoke-report.json"
if (Test-Path $report) { Remove-Item $report }
$env:MXB_DATA_DIR = Join-Path $Root "build\smoke-data"   # never touch the real %APPDATA%\MXB
$exe = Join-Path $Root "dist\MXB\MXB.exe"
$proc = Start-Process -FilePath $exe -ArgumentList "--smoke-test", "`"$report`"" -WorkingDirectory $Root -PassThru
$null = $proc.Handle   # cache the handle, or ExitCode reads back empty after the process exits
if (-not $proc.WaitForExit(300000)) {
  Stop-Process -Id $proc.Id -Force
  throw "Smoke test hung for 5 minutes (an error dialog?). Run dist\MXB\MXB.exe --smoke-test by hand."
}
Remove-Item Env:\MXB_DATA_DIR
if (-not (Test-Path $report)) { throw "Smoke test wrote no report (exit $($proc.ExitCode))" }
$result = Get-Content $report -Raw | ConvertFrom-Json
if (-not $result.ok) {
  Get-Content $report
  throw "Smoke test failed: $($result.failures -join ', ')"
}
Write-Host "Smoke test passed in $($result.seconds)s" -ForegroundColor Green

if ($SkipInstaller) { Write-Host "`nDone: dist\MXB\MXB.exe"; exit 0 }

# 5. Installer ------------------------------------------------------------------------------
Step "Compiling installer"
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
  $roots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles, (Join-Path $env:LOCALAPPDATA "Programs")) | Where-Object { $_ }
  $iscc = $roots | ForEach-Object { Get-ChildItem -Path (Join-Path $_ "Inno Setup*\ISCC.exe") -ErrorAction SilentlyContinue } |
          Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $iscc) { throw "Inno Setup not found. Install it: winget install JRSoftware.InnoSetup  (or choco install innosetup)" }
& $iscc "/DAppVersion=$version" "/DAppVersionNumeric=$numeric" packaging\installer.iss; Check "ISCC"

$setup = Join-Path $Root "dist\MXB-Setup-$version.exe"
if (-not (Test-Path $setup)) { throw "Installer not produced: $setup" }
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
"$hash  MXB-Setup-$version.exe" | Out-File -Encoding ascii (Join-Path $Root "dist\SHA256SUMS.txt")
$size = [math]::Round((Get-Item $setup).Length / 1MB, 1)
Write-Host "`nDone: dist\MXB-Setup-$version.exe ($size MB)`nSHA-256: $hash" -ForegroundColor Green

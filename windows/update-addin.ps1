# Installs (or updates) the BIZOMAT CAD add-in for SOLIDWORKS from the newest BIZOMAT-CAD-SOLIDWORKS*.zip in Downloads
# (or an older OpenSketch-SOLIDWORKS*.zip), and shows which add-in SOLIDWORKS will load. Download the zip first: the
# BIZOMAT CAD for SOLIDWORKS release, or the package on the CAD Automation dashboard.
# From the repository folder:   powershell -ExecutionPolicy Bypass -File windows\update-addin.ps1
#
# It installs into %LOCALAPPDATA%\BIZOMAT CAD\AddIn (up to 0.13: %LOCALAPPDATA%\OpenSketch\AddIn, left as it was): always the same folder, and not on OneDrive (a synced or
# online-only copy can keep SOLIDWORKS on an old file). SOLIDWORKS must be closed: while it runs, the old add-in
# stays loaded.
$ErrorActionPreference = 'Stop'
function Stop-With($message) { Write-Host $message -ForegroundColor Yellow; exit 1 }
$Launcher = 'ed25919a-7e4a-4a08-a2db-4c69ae22b1ea'   # the launcher class the macro starts (COM id unchanged)
$AddIn = '275256ff-b73a-4e4f-9ea8-842b6626d471'      # the add-in class (COM id unchanged)

function Show-Registered {
  foreach ($id in $Launcher, $AddIn) {
    $cb = (Get-ItemProperty "HKCU:\Software\Classes\CLSID\{$id}\InprocServer32" -ErrorAction SilentlyContinue).CodeBase
    if (-not $cb) { Write-Host "  {$id}: not registered"; continue }
    $file = ([Uri]$cb).LocalPath
    $ver = if (Test-Path $file) { (Get-Item $file).VersionInfo.FileVersion } else { 'FILE MISSING' }
    Write-Host "  $ver  $file"
  }
}

Write-Host 'Registered now (what SOLIDWORKS loads):'
Show-Registered

# 1. SOLIDWORKS must be closed, or the old add-in stays loaded
$sw = Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue
if ($sw) {
  $answer = Read-Host 'SOLIDWORKS is running. Save your work, then type y to close it now (anything else stops here)'
  if ($answer -notmatch '^[yY]') { Stop-With 'Close SOLIDWORKS, then run this again.' }
  $sw | Stop-Process -Force
  Start-Sleep -Seconds 3
}

# 2. The newest downloaded zip, and the version inside it
$zip = Get-ChildItem (Join-Path $HOME 'Downloads') -Filter '*-SOLIDWORKS*.zip' -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $zip) {
  Stop-With 'No BIZOMAT-CAD-SOLIDWORKS zip in Downloads. Download it from the CAD Automation dashboard or the BIZOMAT CAD for SOLIDWORKS release.'
}
Write-Host "Using $($zip.FullName) (downloaded $($zip.LastWriteTime))"
$stage = Join-Path $env:TEMP ('bizomat-cad-addin-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
Expand-Archive -Path $zip.FullName -DestinationPath $stage -Force
$src = Get-ChildItem $stage -Recurse -Filter 'OpenSketch.Sw.dll' | Select-Object -First 1
if (-not $src) { Stop-With 'That zip has no OpenSketch.Sw.dll. Download the zip again.' }
$newVersion = [version]$src.VersionInfo.FileVersion
Write-Host "The zip holds add-in $newVersion"
if ($newVersion -lt [version]'0.10.0') {
  Stop-With "That zip is add-in $newVersion, too old for drawings. Download the newest from the BIZOMAT CAD for SOLIDWORKS release, then run this again."
}

# 3. Into one fixed local folder, then register it for this Windows user
$target = Join-Path $env:LOCALAPPDATA 'BIZOMAT CAD\AddIn'
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item (Join-Path $src.DirectoryName '*') $target -Recurse -Force
Get-ChildItem $target | Unblock-File
# BIZOMAT-CAD.exe from 0.14; packages up to 0.13 named it OpenSketchSW.exe
$exe = Join-Path $target 'BIZOMAT-CAD.exe'
if (-not (Test-Path (Join-Path $src.DirectoryName 'BIZOMAT-CAD.exe'))) { $exe = Join-Path $target 'OpenSketchSW.exe' }
$p = Start-Process -FilePath $exe -ArgumentList '--install' -Wait -PassThru -NoNewWindow
if ($p.ExitCode -ne 0) { Stop-With "$(Split-Path $exe -Leaf) --install failed (exit $($p.ExitCode))." }
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

# 4. Proof
Write-Host ''
Write-Host 'Registered now (what SOLIDWORKS loads):'
Show-Registered
$cb = (Get-ItemProperty "HKCU:\Software\Classes\CLSID\{$Launcher}\InprocServer32").CodeBase
$loaded = [version](Get-Item ([Uri]$cb).LocalPath).VersionInfo.FileVersion
if ($loaded -ge [version]'0.10.0') {
  Write-Host "Done: SOLIDWORKS will load add-in $loaded from $target" -ForegroundColor Green
  Write-Host 'Open SOLIDWORKS and connect (the BIZOMAT menu, or Tools > Macro > Run > Documents\BIZOMAT CAD\BIZOMAT CAD.swb).'
} else {
  Stop-With "Still registered: $loaded. Send this window's text to whoever helps you."
}

# The server's home page offers the same zip
$downloads = Join-Path (Split-Path $PSScriptRoot -Parent) 'opensketch\static\downloads'
if (Test-Path (Split-Path $downloads -Parent)) {
  New-Item -ItemType Directory -Force -Path $downloads | Out-Null
  Copy-Item $zip.FullName (Join-Path $downloads 'BIZOMAT-CAD-SOLIDWORKS.zip') -Force
}

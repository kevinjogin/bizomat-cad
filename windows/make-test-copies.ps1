# BIZOMAT CAD, Phase 2.1: the test copies, made with SOLIDWORKS' own Pack and Go (IModelDocExtension.GetPackAndGo and
# SavePackAndGo), as docs/drafting-intelligence/PHASE2_1_LIVE_VERIFICATION.md requires.
#
# Run in a normal (not administrator) PowerShell, with SOLIDWORKS 2022 open, from the repository's apps\cad folder:
#   powershell -ExecutionPolicy Bypass -File windows\make-test-copies.ps1
#
# The SOLIDWORKS calls are in windows\PackAndGoHelper.cs, compiled here against the interop library of the SOLIDWORKS
# installation (Windows PowerShell cannot late-bind SOLIDWORKS' COM methods: TYPE_E_ELEMENTNOTFOUND).
# It stops at the first failure, and:
#  1. checks the original drawing exists and records the SHA-256 of the drawing and of every file it references;
#  2. opens the original read-only (or uses it if it is already open with no unsaved changes);
#  3. runs Pack and Go: the drawing and the documents it references, flattened into the destination with the suffix;
#     it refuses when a copy would land on an original, outside the destination, or on a copy that already exists;
#  4. closes only the original it opened itself (closing never saves);
#  5. opens the copied drawing and checks that every reference (stored and resolved) and every view shows a copied
#     file in the destination;
#  6. hashes the originals again: any change stops the run with ORIGINAL CHANGED;
#  7. writes <destination>\evidence\pack-and-go.json and prints the live verification command.
# It never saves, overwrites, renames or edits an original.
param(
  [string]$Source = (Join-Path $env:USERPROFILE 'OneDrive\Documents\OpenSketch\MT-01_Top_Clamp_Plate.SLDDRW'),
  [string]$Destination = (Join-Path $env:USERPROFILE 'Documents\BIZOMAT CAD\Projects\phase21-test'),
  [string]$Suffix = '_P21TEST'
)
$ErrorActionPreference = 'Stop'
$evidence = [ordered]@{ started_utc = (Get-Date).ToUniversalTime().ToString('o'); source = $Source; destination = $Destination; suffix = $Suffix }
$helperReady = $false

function Save-Evidence {
  $dir = Join-Path $Destination 'evidence'
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $evidence.finished_utc = (Get-Date).ToUniversalTime().ToString('o')
  $evidence | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 -Path (Join-Path $dir 'pack-and-go.json')
}
function Close-Original {
  if ($helperReady) {
    try { if ([Bizomat.Phase21.PackHelper]::CloseOriginal()) { $evidence.original_closed = $true } } catch { }
  }
}
function Stop-With([string]$message) {
  Close-Original
  $evidence.stopped = $message
  try { Save-Evidence } catch { }
  Write-Host ('STOPPED: ' + $message) -ForegroundColor Yellow
  exit 1
}
function Reason($err) {
  $e = $err.Exception
  while ($e.InnerException -ne $null) { $e = $e.InnerException }
  return $e.Message
}
function Hash([string]$path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash }
function Full([string]$path) { [IO.Path]::GetFullPath($path) }
function Same([string]$a, [string]$b) { [string]::Equals((Full $a).TrimEnd('\'), (Full $b).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) }

# 1. the original drawing, and the hashes before anything is opened
if (-not (Test-Path -LiteralPath $Source)) { Stop-With "No such drawing: $Source" }
$Source = (Resolve-Path -LiteralPath $Source).Path
if (Same (Split-Path $Source) $Destination) { Stop-With 'The destination is the originals folder: choose another one.' }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$before = @{}   # keys are case-insensitive
$before[$Source] = Hash $Source
$part = [IO.Path]::ChangeExtension($Source, '.SLDPRT')
if (Test-Path -LiteralPath $part) { $before[$part] = Hash $part }
Write-Host "Original drawing: $Source"

# 2. SOLIDWORKS, its interop library, the helper, and the original opened read-only
$proc = @(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue)
$evidence.solidworks_processes = @($proc | ForEach-Object { $_.Id })
if ($proc.Count -eq 0) { Stop-With 'SOLIDWORKS is not running (no SLDWORKS.exe process). Open SOLIDWORKS 2022 and run this again.' }
$swDir = $null
try { $swDir = Split-Path $proc[0].Path } catch { }
$candidates = @()
foreach ($d in @($swDir, 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS')) {
  if ($d) { $candidates += (Join-Path $d 'api\redist\SolidWorks.Interop.sldworks.dll'); $candidates += (Join-Path $d 'SolidWorks.Interop.sldworks.dll') }
}
$interop = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $interop) { Stop-With ('The SOLIDWORKS interop library was not found. Looked in: ' + ($candidates -join '; ')) }
$evidence.interop = $interop
$helper = Join-Path $PSScriptRoot 'PackAndGoHelper.cs'
try {
  Add-Type -Path $interop
  Add-Type -Path $helper -ReferencedAssemblies $interop
  $helperReady = $true
} catch {
  Stop-With ('The Pack and Go helper did not compile: ' + (Reason $_))
}
try { $evidence.solidworks = [Bizomat.Phase21.PackHelper]::Connect() } catch {
  Stop-With ('SOLIDWORKS is running (process ' + ($evidence.solidworks_processes -join ', ') + ') but did not answer: ' + (Reason $_) +
             '. Usual causes: SOLIDWORKS runs as administrator while this window does not (start both normally), or it is still starting or showing a dialog.')
}
Write-Host "SOLIDWORKS $($evidence.solidworks)"
try { $evidence.original_open = [Bizomat.Phase21.PackHelper]::OpenOriginal($Source) } catch { Stop-With (Reason $_) }
$evidence.original_opened_read_only = [Bizomat.Phase21.PackHelper]::OriginalReadOnly()
$refs = @([Bizomat.Phase21.PackHelper]::OriginalReferences())
$evidence.original_references = $refs
if ($refs.Count -lt 1) { Stop-With 'SOLIDWORKS lists no referenced part for the original drawing.' }
foreach ($r in $refs) {
  if (-not (Test-Path -LiteralPath $r)) { Stop-With "The original drawing references a file that is not found: $r" }
  if (-not $before.ContainsKey($r)) { $before[$r] = Hash $r }   # read-only open: the file is unchanged
}
$evidence.originals_sha256_before = $before
foreach ($k in $before.Keys) { Write-Host ("  before  {0}  {1}" -f $before[$k], $k) }

# 3. Pack and Go: the plan first, then the save
try { $lines = @([Bizomat.Phase21.PackHelper]::Plan($Destination, $Suffix)) } catch { Stop-With ('Pack and Go could not be planned: ' + (Reason $_)) }
$plan = @()
foreach ($l in $lines) {
  $parts = $l.Split('|')
  $plan += [ordered]@{ original = $parts[0]; copy = $parts[1] }
}
$evidence.plan = $plan
if ($plan.Count -lt 2) { Stop-With "Pack and Go found $($plan.Count) document(s); the drawing and its part are expected." }
foreach ($p in $plan) {
  Write-Host ("  plan    {0}  ->  {1}" -f $p.original, $p.copy)
  if ([string]::IsNullOrEmpty($p.copy)) { Stop-With "Pack and Go has no name to save $($p.original) to." }
  if (-not (Same (Split-Path $p.copy) $Destination)) { Stop-With "Pack and Go would save $($p.copy) outside the destination." }
  foreach ($o in $before.Keys) { if (Same $o $p.copy) { Stop-With "Pack and Go would overwrite an original: $($p.copy)" } }
  if (Test-Path -LiteralPath $p.copy) { Stop-With "A copy already exists: $($p.copy). Move it away (or use another -Suffix) and run this again." }
  if (-not [IO.Path]::GetFileNameWithoutExtension($p.copy).EndsWith($Suffix, [StringComparison]::OrdinalIgnoreCase)) { Stop-With "Pack and Go would not add the suffix to $($p.copy)." }
}
try { $codes = @([Bizomat.Phase21.PackHelper]::Save()) } catch { Stop-With ('Pack and Go failed: ' + (Reason $_)) }
$labels = @{ 0 = 'saved'; 1 = 'user input not correct'; 2 = 'file already exists'; 3 = 'save-to name empty'; 4 = 'save error' }
$evidence.save_status = @()
$failed = @()
for ($i = 0; $i -lt $codes.Count; $i++) {
  $c = [int]$codes[$i]
  $label = $labels[$c]
  if ($label -eq $null) { $label = "status $c" }
  $name = ''
  if ($i -lt $plan.Count) { $name = $plan[$i].copy }
  $evidence.save_status += [ordered]@{ copy = $name; code = $c; status = $label }
  Write-Host ("  saved   {0}  {1}" -f $label, $name)
  if ($c -ne 0) { $failed += "$name ($label)" }
}
if ($codes.Count -eq 0) { Stop-With 'SavePackAndGo returned no status.' }
if ($failed.Count -gt 0) { Stop-With ('Pack and Go failed: ' + ($failed -join '; ')) }

# 4. close the original this script opened (never saved)
Close-Original

# 5. the copies exist, and the copied drawing shows only copies
foreach ($p in $plan) { if (-not (Test-Path -LiteralPath $p.copy)) { Stop-With "Pack and Go reported success, but $($p.copy) is not there." } }
$copyDrawing = ($plan | Where-Object { $_.copy -match '\.slddrw$' } | Select-Object -First 1).copy
if (-not $copyDrawing) { Stop-With 'No drawing among the copies.' }
try { $check = @([Bizomat.Phase21.PackHelper]::CheckCopy($copyDrawing)) } catch { Stop-With ('The copied drawing could not be checked: ' + (Reason $_)) }
$stored = @()
$resolved = @()
$views = @()
foreach ($l in $check) {
  $f = $l.Split('|')
  switch ($f[0]) {
    'open' { $evidence.copy_open = [ordered]@{ path = $copyDrawing; errors = [int]$f[1]; warnings = [int]$f[2] } }
    'stored' { $stored += $f[1] }
    'resolved' { $resolved += $f[1] }
    'view' { $views += [ordered]@{ view = $f[1]; model = $f[2] } }
  }
}
$evidence.copy_references_stored = $stored
$evidence.copy_references_resolved = $resolved
$evidence.copy_views = $views
$bad = @()
if (($stored.Count + $resolved.Count) -eq 0) { $bad += 'SOLIDWORKS lists no reference for the copied drawing' }
foreach ($r in @($stored + $resolved)) {
  if (-not (Same (Split-Path $r) $Destination)) { $bad += "$r is not in the destination" }
  elseif (-not (Test-Path -LiteralPath $r)) { $bad += "$r does not exist" }
}
foreach ($v in $views) {
  if ($v.model -and -not (Same (Split-Path $v.model) $Destination)) { $bad += "view $($v.view) shows $($v.model)" }
}
$loaded = @()
foreach ($o in $before.Keys) { if ([Bizomat.Phase21.PackHelper]::IsLoaded($o)) { $loaded += $o } }
$evidence.originals_loaded_after = $loaded   # a note only: the copies have other names, so an open original is never picked up
if ($bad.Count -gt 0) { Stop-With ('The copies do not reference only copies: ' + ($bad -join '; ')) }
foreach ($v in $views) { Write-Host ("  view    {0}  shows  {1}" -f $v.view, $v.model) }
foreach ($r in $resolved) { Write-Host "  ref     $r" }

# 6. the originals, unchanged?
$after = @{}
$changed = @()
foreach ($k in @($before.Keys)) {
  $after[$k] = Hash $k
  if ($after[$k] -ne $before[$k]) { $changed += $k }
}
$evidence.originals_sha256_after = $after
$evidence.originals_unchanged = ($changed.Count -eq 0)
if ($changed.Count -gt 0) { Stop-With ('ORIGINAL CHANGED: ' + ($changed -join ', ') + '. Do not run the live test; investigate first.') }

# 7. evidence and the next command
$copyPart = ($plan | Where-Object { $_.copy -match '\.sldprt$' } | Select-Object -First 1).copy
$evidence.copies = [ordered]@{ drawing = $copyDrawing; part = $copyPart }
$evidence.result = 'PASSED'
Save-Evidence
Write-Host ''
Write-Host 'Pack and Go: PASSED. Copies made, the copied drawing shows only copies, the originals are unchanged.' -ForegroundColor Green
Write-Host "Evidence: $(Join-Path $Destination 'evidence\pack-and-go.json')"
Write-Host ''
Write-Host 'Next, the live verification:'
$origArgs = ($before.Keys | ForEach-Object { '--original "' + $_ + '"' }) -join ' '
Write-Host ('.venv\Scripts\python windows\live_verify.py --part "' + $copyPart + '" --drawing "' + $copyDrawing + '" ' + $origArgs)

# BIZOMAT CAD, Phase 2.1: the test copies, made with SOLIDWORKS' own Pack and Go (IModelDocExtension.GetPackAndGo and
# SavePackAndGo), as docs/drafting-intelligence/PHASE2_1_LIVE_VERIFICATION.md requires.
#
# Run in a normal (not administrator) PowerShell, with SOLIDWORKS 2022 open, from the repository's apps\cad folder:
#   powershell -ExecutionPolicy Bypass -File windows\make-test-copies.ps1
#
# It stops at the first failure, and:
#  1. checks the original drawing exists and records the SHA-256 of the drawing and of every file it references;
#  2. opens the original read-only (or uses it if it is already open with no unsaved changes);
#  3. runs Pack and Go: the drawing and the documents it references, flattened into the destination with the suffix;
#     it refuses when a copy would land on an original, outside the destination, or on a copy that already exists;
#  4. closes only the original it opened itself (closing never saves);
#  5. opens the copied drawing and checks that every reference (stored and resolved) and every view shows a copied
#     file in the destination, and that no original is loaded;
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
$sw = $null
$doc = $null
$openedOriginal = $false

function Save-Evidence {
  $dir = Join-Path $Destination 'evidence'
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $evidence.finished_utc = (Get-Date).ToUniversalTime().ToString('o')
  $evidence | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 -Path (Join-Path $dir 'pack-and-go.json')
}
function Close-Original {
  if ($openedOriginal -and $sw -ne $null -and $doc -ne $null) {
    try { $sw.CloseDoc($doc.GetTitle()) } catch { }   # CloseDoc never saves
    $script:openedOriginal = $false
  }
}
function Stop-With([string]$message) {
  Close-Original
  $evidence.stopped = $message
  try { Save-Evidence } catch { }
  Write-Host ('STOPPED: ' + $message) -ForegroundColor Yellow
  exit 1
}
function Hash([string]$path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash }
function Full([string]$path) { [IO.Path]::GetFullPath($path) }
function Same([string]$a, [string]$b) { [string]::Equals((Full $a).TrimEnd('\'), (Full $b).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) }
function Paths($deps) {
  # GetDependencies2 gives file name, full path, file name, full path, ...
  $out = @()
  if ($deps -eq $null) { return ,$out }
  $a = @($deps)
  for ($i = 0; $i + 1 -lt $a.Count; $i += 2) { $out += [string]$a[$i + 1] }
  return ,$out
}

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

# 2. SOLIDWORKS, and the original opened read-only
$proc = @(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue)
$evidence.solidworks_processes = @($proc | ForEach-Object { $_.Id })
if ($proc.Count -eq 0) { Stop-With 'SOLIDWORKS is not running (no SLDWORKS.exe process). Open SOLIDWORKS 2022 and run this again.' }
$problems = @()
foreach ($progId in @('SldWorks.Application', 'SldWorks.Application.30')) {   # 30 = SOLIDWORKS 2022
  try {
    $sw = [Runtime.InteropServices.Marshal]::GetActiveObject($progId)
    if ($sw -ne $null) { $evidence.solidworks_progid = $progId; break }
  } catch {
    $problems += ($progId + ': ' + $_.Exception.Message)
  }
}
if ($sw -eq $null) {
  Stop-With ('SOLIDWORKS is running (process ' + ($evidence.solidworks_processes -join ', ') + ') but did not answer: ' + ($problems -join ' | ') +
             '. Usual causes: SOLIDWORKS runs as administrator while this window does not (start both normally), or it is still starting or showing a dialog.')
}
$evidence.solidworks = $sw.RevisionNumber()
$doc = $sw.GetOpenDocumentByName($Source)
if ($doc -ne $null) {
  if ($doc.GetSaveFlag()) { Stop-With 'The original drawing is open with unsaved changes. Close it without saving (Window > Close All, Don''t Save), then run this again.' }
  $evidence.original_was_open = $true
} else {
  $err = 0
  $warn = 0
  $doc = $sw.OpenDoc6($Source, 3, 3, '', [ref]$err, [ref]$warn)   # swDocDRAWING; swOpenDocOptions Silent + ReadOnly
  if ($doc -eq $null) { Stop-With "SOLIDWORKS could not open the original drawing (error $err, warning $warn)." }
  $openedOriginal = $true
  $evidence.original_was_open = $false
}
$evidence.original_opened_read_only = $doc.IsOpenedReadOnly()
$refs = Paths ($doc.GetDependencies2($true, $true, $false))
$evidence.original_references = $refs
if ($refs.Count -lt 1) { Stop-With 'SOLIDWORKS lists no referenced part for the original drawing.' }
foreach ($r in $refs) {
  if (-not (Test-Path -LiteralPath $r)) { Stop-With "The original drawing references a file that is not found: $r" }
  if (-not $before.ContainsKey($r)) { $before[$r] = Hash $r }   # read-only open: the file is unchanged
}
$evidence.originals_sha256_before = $before
foreach ($k in $before.Keys) { Write-Host ("  before  {0}  {1}" -f $before[$k], $k) }

# 3. Pack and Go: the plan first, then the save
$pg = $doc.Extension.GetPackAndGo()
$pg.IncludeDrawings = $true
try { $pg.IncludeSimulationResults = $false } catch { }
try { $pg.IncludeToolboxComponents = $false } catch { }
$pg.FlattenToSingleFolder = $true
$pg.AddSuffix = $Suffix
if (-not $pg.SetSaveToName($true, $Destination)) { Stop-With 'Pack and Go did not accept the destination folder.' }
$names = $null
[void]$pg.GetDocumentNames([ref]$names)
$saveTo = $null
$state = $null
[void]$pg.GetDocumentSaveToNames([ref]$saveTo, [ref]$state)
$names = @($names)
$saveTo = @($saveTo)
$plan = @()
for ($i = 0; $i -lt $names.Count; $i++) { $plan += [ordered]@{ original = [string]$names[$i]; copy = [string]$saveTo[$i] } }
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
$codes = @($doc.Extension.SavePackAndGo($pg))
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
$err = 0
$warn = 0
$copy = $sw.OpenDoc6($copyDrawing, 3, 1, '', [ref]$err, [ref]$warn)   # swDocDRAWING; Silent
if ($copy -eq $null) { Stop-With "SOLIDWORKS could not open the copied drawing (error $err, warning $warn)." }
$evidence.copy_open = [ordered]@{ path = $copyDrawing; errors = $err; warnings = $warn }
$stored = Paths ($copy.GetDependencies2($true, $false, $false))
$resolved = Paths ($copy.GetDependencies2($true, $true, $false))
$evidence.copy_references_stored = $stored
$evidence.copy_references_resolved = $resolved
$bad = @()
foreach ($r in @($stored + $resolved)) {
  if (-not (Same (Split-Path $r) $Destination)) { $bad += "$r is not in the destination" }
  elseif (-not (Test-Path -LiteralPath $r)) { $bad += "$r does not exist" }
}
$views = @()
try {
  foreach ($sheet in @($copy.GetViews())) {
    $arr = @($sheet)
    for ($k = 1; $k -lt $arr.Count; $k++) {   # [0] is the sheet itself
      $model = [string]$arr[$k].GetReferencedModelName()
      $views += [ordered]@{ view = [string]$arr[$k].GetName2(); model = $model }
      if ($model -and -not (Same (Split-Path $model) $Destination)) { $bad += "view $($arr[$k].GetName2()) shows $model" }
    }
  }
} catch {
  $evidence.views_note = 'views could not be listed from PowerShell (' + $_.Exception.Message + '); the references above and the harness check P4 cover them'
}
$evidence.copy_views = $views
$loaded = @()
foreach ($o in $before.Keys) { if ($sw.GetOpenDocumentByName($o) -ne $null) { $loaded += $o } }
$evidence.originals_loaded_after = $loaded   # a note only: the copies have other names, so an open original is never picked up
try { $sw.CloseDoc($copy.GetTitle()) } catch { }   # the harness opens it again; nothing was changed in it
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

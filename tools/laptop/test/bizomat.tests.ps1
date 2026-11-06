<#
  Tests of bizomat.ps1's CAD Automation commands (move, back, sync, retire, delete, and the checks deploy website and
  deploy cad make), with fly, node, git and the prompts replaced by test functions: nothing reaches Fly, GitHub or
  the network. Windows PowerShell 5.1 and PowerShell 7:

    powershell -NoProfile -ExecutionPolicy Bypass -File tools\laptop\test\bizomat.tests.ps1
    pwsh -NoProfile -File tools/laptop/test/bizomat.tests.ps1

  The move itself (infrastructure/migrate/cad/to-fly.mjs) is rehearsed in gocore-website
  (infrastructure/migrate/test/cad-move/rehearse.sh); this checks what the laptop decides and when it asks.
#>
$ErrorActionPreference = 'Stop'
$script:passed = 0
$script:failed = 0
function Check([string] $What, [scriptblock] $Test) {
    $ok = $false
    $why = ''
    try { $ok = [bool](& $Test) } catch { $ok = $false; $why = $_.Exception.Message }
    if ($ok) { $script:passed++; Write-Host "ok    $What" }
    else { $script:failed++; Write-Host "FAIL  $What $(if ($why) { "($why)" })" -ForegroundColor Red }
}
function Stops([scriptblock] $Block, [string] $Like) {
    # $true when the block stops (Stop-Here) with a message matching $Like
    try { & $Block | Out-Null } catch { return ($_.Exception.Message -like "STOP: *$Like*") }
    return $false
}

# bizomat.ps1's functions, without running a command (its help goes nowhere)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path (Split-Path -Parent $here) 'bizomat.ps1') 'help' *> $null
Set-StrictMode -Version 2.0

$tmp = Join-Path ([IO.Path]::GetTempPath()) ('bizomat-tests-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
[void](New-Item -ItemType Directory -Path $tmp)
$Root = $tmp
$site = Join-Path $tmp 'gocore-website'
$cadosDir = Join-Path $tmp 'CADOS'
foreach ($d in @("$site\infrastructure\migrate\cad", "$site\apps", $cadosDir)) { [void](New-Item -ItemType Directory -Force -Path $d) }
Set-Content -LiteralPath "$site\infrastructure\migrate\cad\to-fly.mjs" -Value '// stand-in'
$pinCommit = 'abc1234' + ('0' * 33)
Set-Content -LiteralPath "$site\apps\cad-source.json" -Value ('{"repository": "jogkev-creator/CADOS", "commit": "' + $pinCommit + '", "tree": "' + ('1' * 40) + '"}')
$OldUrl = 'http://cados.internal:8080'
$NewUrl = 'http://cad.process.bizomat.internal:8001'
function Set-Toml([string] $Upstream, [bool] $Cad = $true) {
    $lines = @('[processes]', '  proxy = "x"', '  web = "x"', '  work = "x"')
    if ($Cad) { $lines += '  cad = "/usr/local/bin/bizomat-entrypoint cad"' }
    $lines += @('[env]', "  UPSTREAM_CAD = `"$Upstream`"", '[[mounts]]', '  source = "work_data"')
    if ($Cad) { $lines += @('[[mounts]]', '  source = "cad_data"') }
    Set-Content -LiteralPath "$site\fly.website.toml" -Value $lines
}

# --------------------------------------------------------------------------- the stand-ins
$script:calls = New-Object System.Collections.ArrayList
$script:status = $null      # what to-fly.mjs status --json reports
$script:nodeExit = 0
$script:answer = ''
$script:gitDiff = ''
$script:machinesJson = '[]'
function Stop-Here([string] $Text) { throw "STOP: $Text" }
function Read-Host { param([string] $Prompt, [switch] $AsSecureString) return $script:answer }
$script:failApply = $false
function node {
    $line = ($args -join ' ')
    if ($line -eq '--version') { Write-Output 'v22.20.0'; $global:LASTEXITCODE = 0; return }
    [void]$script:calls.Add('node ' + $line)
    if ($line -match ' status --json$' -and $script:status) { Write-Output 'a line of noise'; Write-Output ($script:status | ConvertTo-Json -Compress -Depth 5) }
    $global:LASTEXITCODE = $(if ($script:failApply -and $line -match ' apply ') { 1 } else { $script:nodeExit })
}
function fly {
    [void]$script:calls.Add('fly ' + ($args -join ' '))
    if ($args[0] -eq 'machines' -and $args[1] -eq 'list') { Write-Output $script:machinesJson }
    $global:LASTEXITCODE = 0
}
function git {
    [void]$script:calls.Add('git ' + ($args -join ' '))
    if ($args[0] -eq 'cat-file') { $global:LASTEXITCODE = $(if ("$($args[2])" -like 'abc1234*') { 0 } else { 1 }); return }
    if ($args[0] -eq 'diff') { if ($script:gitDiff) { Write-Output $script:gitDiff }; $global:LASTEXITCODE = 0; return }
    $global:LASTEXITCODE = 0
}
function Get-DeployCommit([string] $Repo) {
    $dir = if ($Repo -eq 'CADOS') { $cadosDir } else { $site }
    return @{ Repo = $Repo; Dir = $dir; Branch = 'main'; Commit = $pinCommit; Short = 'abc1234'; Subject = 'a commit'; When = '2026-11-07 10:00' }
}
function Get-Checks { return 'passed' }
function Get-Json([string] $Url) { return $null }
function Get-Code { return 0 }
function npm { $global:LASTEXITCODE = 0 }
function State([string] $Route, $Cad = @{ machine = 'm1'; state = 'started'; region = 'syd'; image = 'bizomat-abc1234' }) {
    $up = @()
    if ($Route -eq 'old') { $up = @($OldUrl) } elseif ($Route -eq 'new') { $up = @($NewUrl) }
    # as to-fly.mjs status --json gives it: JSON, read back into objects
    return (@{ route = $Route; upstream = $up; old_url = $OldUrl; new_url = $NewUrl; cad = $Cad; old = @{ machine = 'm0'; state = 'started'; region = 'ams'; autostart = $true } } | ConvertTo-Json -Depth 5 | ConvertFrom-Json)
}

try {
    # Windows PowerShell 5.1 reads a script without a byte order mark as the system code page: ASCII only
    $bytes = [IO.File]::ReadAllBytes((Join-Path (Split-Path -Parent $here) 'bizomat.ps1'))
    Check 'bizomat.ps1 is plain ASCII' { [Array]::FindIndex($bytes, [Predicate[byte]] { param($b) $b -gt 126 }) -lt 0 }

    # --------------------------------------------------------------------- reading things
    Set-Toml $OldUrl
    Check 'Get-TomlValue reads UPSTREAM_CAD' { (Get-TomlValue "$site\fly.website.toml" 'UPSTREAM_CAD') -eq $OldUrl }
    Check 'Get-CadPin reads apps/cad-source.json' { "$(Get-Prop (Get-CadPin $site) 'commit')" -eq $pinCommit }
    $script:status = State 'old'
    Check 'Get-CadState takes the JSON line of to-fly.mjs status' { "$(Get-Prop (Get-CadState $site) 'route')" -eq 'old' }
    $script:status = $null
    Check 'Get-CadState is $null when the tool says nothing' { $null -eq (Get-CadState $site) }

    # --------------------------------------------------------------------- deploy website: the route must not move
    Set-Toml $OldUrl
    $script:status = State 'old'
    Check 'route check: router and fly.website.toml agree (cados)' { -not (Stops { Assert-CadRoute $site } '') }
    $script:status = State 'new'
    Check 'route check: after move cad, a fly.website.toml still on cados is refused' { Stops { Assert-CadRoute $site } 'still sends bizomat.ai/cad to cados' }
    Set-Toml $NewUrl
    $script:status = State 'old'
    Check 'route check: fly.website.toml on the cad group before move cad is refused' { Stops { Assert-CadRoute $site } 'holding page' }
    $script:status = State 'new'
    Check 'route check: router and fly.website.toml agree (cad group)' { -not (Stops { Assert-CadRoute $site } '') }
    $script:status = State 'none' $null
    Check 'route check: no router yet (first deploy) passes' { -not (Stops { Assert-CadRoute $site } '') }

    # --------------------------------------------------------------------- deploy website: does cad restart?
    Set-Toml $OldUrl $false
    Check 'groups: no cad group in fly.website.toml' { (Get-CadGroups $site (State 'old')) -eq 'proxy,web,work' }
    Set-Toml $OldUrl
    Check 'groups: a new cad group is deployed' { (Get-CadGroups $site (State 'old' $null)) -eq 'proxy,web,work,cad' }
    $script:gitDiff = ''
    Check 'groups: cad unchanged since the commit it runs is left alone' { (Get-CadGroups $site (State 'old')) -eq 'proxy,web,work' }
    $script:gitDiff = "apps/cad/opensketch/server.py`ninfrastructure/fly/entrypoint.sh"
    Check 'groups: cad changed since the commit it runs restarts' { (Get-CadGroups $site (State 'old')) -eq 'proxy,web,work,cad' }
    Check 'groups: an image without a commit tag restarts cad' { (Get-CadGroups $site (State 'old' @{ machine = 'm1'; state = 'started'; region = 'syd'; image = 'deployment-01ABC' })) -eq 'proxy,web,work,cad' }
    Check 'groups: a commit this folder does not have restarts cad' { (Get-CadGroups $site (State 'old' @{ machine = 'm1'; state = 'started'; region = 'syd'; image = 'bizomat-fff0000' })) -eq 'proxy,web,work,cad' }

    # --------------------------------------------------------------------- deploy website: what it runs
    Set-Toml $OldUrl
    $script:status = State 'old' $null
    $DryRun = $false; $SkipChecks = $true; $script:answer = 'yes'
    function Read-Host { param([string] $Prompt, [switch] $AsSecureString) return 'yes' }
    function Wait-Until([scriptblock] $Test, [int] $Seconds) { return $true }
    $script:calls.Clear()
    try { Deploy-Website *> $null } catch { }   # its live checks then fail against the stand-ins: expected here
    Check 'deploy website: a first deploy with the cad group deploys every group (no --process-groups)' {
        $d = @($script:calls) -match '^fly deploy'
        $d.Count -eq 1 -and ($d[0] -notmatch '--process-groups') -and ($d[0] -match '--image-label bizomat-abc1234')
    }
    Check 'deploy website: the cad volume is made first' { (@($script:calls) -match '^fly volumes create cad_data --region syd').Count -eq 1 }
    $script:gitDiff = ''
    $script:status = State 'old'
    $script:calls.Clear()
    try { Deploy-Website *> $null } catch { }
    Check 'deploy website: cad unchanged since the commit it runs is left running (--process-groups proxy,web,work)' {
        (@($script:calls) -match '^fly deploy .*--process-groups proxy,web,work( |$)').Count -eq 1
    }
    $SkipChecks = $false
    Remove-Item function:Wait-Until
    . (Join-Path (Split-Path -Parent $here) 'bizomat.ps1') 'help' *> $null   # the real ones again
    function Stop-Here([string] $Text) { throw "STOP: $Text" }
    function Read-Host { param([string] $Prompt, [switch] $AsSecureString) return $script:answer }
    function Get-DeployCommit([string] $Repo) { $dir = if ($Repo -eq 'CADOS') { $cadosDir } else { $site }; return @{ Repo = $Repo; Dir = $dir; Branch = 'main'; Commit = $pinCommit; Short = 'abc1234'; Subject = 'a commit'; When = '2026-11-07 10:00' } }
    function Get-Checks { return 'passed' }
    function Get-Json([string] $Url) { return $null }
    function Get-Code { return 0 }
    Set-StrictMode -Version 2.0
    $Root = $tmp

    # --------------------------------------------------------------------- deploy cad: where it goes
    $script:routeTo = ''
    function Deploy-CadGroup($Site) { $script:routeTo = 'group' }
    function Deploy-Cados { $script:routeTo = 'cados' }
    $script:status = State 'new'
    Deploy-Cad
    Check 'deploy cad after move cad deploys the cad group' { $script:routeTo -eq 'group' }
    $script:status = State 'old'
    Deploy-Cad
    Check 'deploy cad before move cad deploys cados' { $script:routeTo -eq 'cados' }
    $script:status = State 'mixed'
    Check 'deploy cad refuses an unclear route' { Stops { Deploy-Cad } 'neither cados nor the cad group' }
    Remove-Item function:Deploy-CadGroup, function:Deploy-Cados
    . (Join-Path (Split-Path -Parent $here) 'bizomat.ps1') 'help' *> $null   # the real ones again
    function Stop-Here([string] $Text) { throw "STOP: $Text" }
    function Read-Host { param([string] $Prompt, [switch] $AsSecureString) return $script:answer }
    function Get-DeployCommit([string] $Repo) { $dir = if ($Repo -eq 'CADOS') { $cadosDir } else { $site }; return @{ Repo = $Repo; Dir = $dir; Branch = 'main'; Commit = $pinCommit; Short = 'abc1234'; Subject = 'a commit'; When = '2026-11-07 10:00' } }
    function Get-Checks { return 'passed' }
    function Get-Json([string] $Url) { return $null }
    function Get-Code { return 0 }
    Set-StrictMode -Version 2.0
    $Root = $tmp

    # the old path never starts cados again once move cad has stopped it
    $script:machinesJson = '[{"id": "m0", "state": "stopped", "config": {"services": [{"autostart": false, "autostop": "off"}]}}]'
    Check 'deploy cad refuses to deploy cados after move cad stopped it' { Stops { Deploy-Cados } 'stopped by move cad' }
    $script:machinesJson = '[{"id": "m0", "state": "started", "config": {"services": [{"autostart": true, "autostop": "suspend"}]}}]'
    $DryRun = $true
    $script:calls.Clear()
    Check 'deploy cad to cados still works before the move (dry run: no deploy)' { -not (Stops { Deploy-Cados } '') -and -not (@($script:calls) -match '^fly deploy') }
    $DryRun = $false

    # --------------------------------------------------------------------- deploy cad (group): apps/cad must be CADOS main
    function Get-DeployCommit([string] $Repo) { $dir = if ($Repo -eq 'CADOS') { $cadosDir } else { $site }; $commit = if ($Repo -eq 'CADOS') { 'def5678' + ('0' * 33) } else { $pinCommit }; return @{ Repo = $Repo; Dir = $dir; Branch = 'main'; Commit = $commit; Short = $commit.Substring(0, 7); Subject = 'a commit'; When = '2026-11-07 10:00' } }
    Check 'deploy cad refuses while apps/cad is not CADOS main' { Stops { Deploy-CadGroup (Get-DeployCommit 'gocore-website') } 'sync cad' }
    function Get-DeployCommit([string] $Repo) { $dir = if ($Repo -eq 'CADOS') { $cadosDir } else { $site }; return @{ Repo = $Repo; Dir = $dir; Branch = 'main'; Commit = $pinCommit; Short = 'abc1234'; Subject = 'a commit'; When = '2026-11-07 10:00' } }

    # --------------------------------------------------------------------- move, back, retire, delete: what they ask
    $script:status = State 'old'
    $script:calls.Clear(); $DryRun = $true
    Move-Cad *> $null
    Check 'move cad -DryRun: check only' { (@($script:calls) -match ' check ').Count -eq 1 -and (@($script:calls) -match ' apply ').Count -eq 0 }
    $DryRun = $false
    $script:calls.Clear(); $script:answer = 'no'
    Move-Cad *> $null
    Check 'move cad: anything but yes stops before the move' { (@($script:calls) -match ' apply ').Count -eq 0 }
    $script:calls.Clear(); $script:answer = 'yes'; $Force = $true
    Move-Cad *> $null
    Check 'move cad: yes moves; -Force is passed on' { (@($script:calls) -match ' apply .* --force$').Count -eq 1 }
    $Force = $false
    Check 'move cad: the move is in deploy-log.csv' { (Get-Content -LiteralPath (Join-Path $Root 'deploy-log.csv') -Raw) -match 'cad-move' }
    $script:calls.Clear(); $script:failApply = $true
    Check 'move cad: a move that stops says so and names the way back' { Stops { Move-Cad *> $null } 'back cad' }
    $script:failApply = $false

    $movesDir = Join-Path $Root 'moves'
    [void](New-Item -ItemType Directory -Force -Path (Join-Path $movesDir 'cad-20261107-100000'))
    Set-Content -LiteralPath (Join-Path $movesDir 'cad-20261107-100000\move.json') -Value '{"moved": "2026-11-07T10:05:00.000Z"}'
    [void](New-Item -ItemType Directory -Force -Path (Join-Path $movesDir 'cad-20261108-090000'))
    Check 'Get-LatestMove: the newest folder with a finished move' { (Get-LatestMove) -like '*cad-20261107-100000' }
    $script:calls.Clear(); $script:answer = 'nope'
    Back-Cad *> $null
    Check 'back cad: anything but yes changes nothing' { (@($script:calls) -match ' back ').Count -eq 0 }
    $script:calls.Clear(); $script:answer = 'yes'
    Back-Cad *> $null
    Check 'back cad: yes takes it back, with the move''s folder' { (@($script:calls) -match ' back .*cad-20261107-100000').Count -eq 1 }

    $script:calls.Clear(); $script:answer = 'yes'
    Retire-Cados *> $null
    Check 'retire cados: yes is not enough (the phrase is release cados)' { (@($script:calls) -match '--confirm').Count -eq 0 -and (@($script:calls) -match 'retire-ips$').Count -eq 1 }
    $script:calls.Clear(); $script:answer = 'release cados'
    Retire-Cados *> $null
    Check 'retire cados: release cados releases' { (@($script:calls) -match 'retire-ips --confirm cados$').Count -eq 1 }
    $script:calls.Clear(); $script:answer = 'release cados'
    Delete-Cados *> $null
    Check 'delete cados: another phrase (delete cados) is needed' { (@($script:calls) -match '--confirm').Count -eq 0 }
    $script:calls.Clear(); $script:answer = 'delete cados'
    Delete-Cados *> $null
    Check 'delete cados: delete cados deletes' { (@($script:calls) -match 'delete-app --confirm cados$').Count -eq 1 }
    $script:calls.Clear(); $DryRun = $true; $script:answer = 'delete cados'
    Delete-Cados *> $null
    Retire-Cados *> $null
    Check 'retire and delete -DryRun: previews only' { (@($script:calls) -match '--confirm').Count -eq 0 }
    $DryRun = $false

    # --------------------------------------------------------------------- sync cad
    $script:calls.Clear()
    Sync-Cad *> $null
    Check 'sync cad: apps/cad already CADOS main changes nothing' { (@($script:calls) -match '^git (switch|commit|push)').Count -eq 0 }
    function Get-DeployCommit([string] $Repo) { $dir = if ($Repo -eq 'CADOS') { $cadosDir } else { $site }; $commit = if ($Repo -eq 'CADOS') { 'def5678' + ('0' * 33) } else { $pinCommit }; return @{ Repo = $Repo; Dir = $dir; Branch = 'main'; Commit = $commit; Short = $commit.Substring(0, 7); Subject = 'a commit'; When = '2026-11-07 10:00' } }
    $script:calls.Clear(); $DryRun = $true
    Sync-Cad *> $null
    Check 'sync cad -DryRun: no branch' { (@($script:calls) -match '^git (switch|commit|push)').Count -eq 0 }
    $DryRun = $false
    $script:calls.Clear(); $script:answer = 'yes'
    Sync-Cad *> $null
    Check 'sync cad: a branch with the copy, pushed, then back on main' {
        $c = @($script:calls)
        ($c -match '^git switch -c cad-sync-def5678$').Count -eq 1 -and ($c -match 'sync-cad.mjs to def5678').Count -eq 1 -and
        ($c -match '^git push -u origin cad-sync-def5678$').Count -eq 1 -and ($c -match '^git switch main$').Count -eq 1
    }
} finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host "bizomat.ps1 tests: $script:passed passed, $script:failed failed"
if ($script:failed -gt 0) { exit 1 }

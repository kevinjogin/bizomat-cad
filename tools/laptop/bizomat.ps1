<#
.SYNOPSIS
  BIZOMAT from your own computer: one folder holding the three repositories, and every deploy made from it.

.DESCRIPTION
  Keep this file in the folder that holds everything (for example C:\BIZOMAT), then run:

    .\bizomat.ps1 setup            clone CADOS, gocore-website and PMO next to this file, or bring them up to date
    .\bizomat.ps1 status           each folder's state, GitHub's checks and what is live
    .\bizomat.ps1 deploy website   the Fly app bizomat: the website, the router behind bizomat.ai, Project Management and
                                   CAD Automation's group (restarted only when its code or scripts changed)
    .\bizomat.ps1 deploy cad       CAD Automation (bizomat.ai/cad): after move cad, the cad group of the Fly app bizomat
                                   with apps/cad = CADOS main; before it, the Fly app cados
    .\bizomat.ps1 deploy tasks     Project Management: Cloudflare Worker workos-platform-preview (work.kevos.com)
    .\bizomat.ps1 sync cad         apps/cad in gocore-website becomes CADOS main, byte for byte: a branch on GitHub to
                                   merge (the cad group is built from apps/cad)
    .\bizomat.ps1 move cad         CAD Automation's data from the Fly app cados (Amsterdam) to the cad group of the Fly
                                   app bizomat (Sydney), and bizomat.ai/cad with it: checks everything and copies the
                                   data while cados runs, then asks before the move (a few minutes off line)
    .\bizomat.ps1 back cad         the way back after move cad: bizomat.ai/cad served by cados again
    .\bizomat.ps1 retire cados     once CAD Automation works from the cad group: release cados's public addresses
    .\bizomat.ps1 delete cados     later, at the end of the rollback window: delete the Fly app cados and its volume
    .\bizomat.ps1 secrets website  the website's Workers AI access on Fly (the assistant and AI search): asks for
                                   the Cloudflare account ID and token, checks them, saves them on Fly
    .\bizomat.ps1 move tasks       Project Management's data from Cloudflare to the Fly app bizomat (bizomat.ai/tasks):
                                   exports and checks it (Cloudflare only read), then asks before it changes Fly
    .\bizomat.ps1 restore kevos    kevos.com back to the KEVOS site (Cloudflare), as it was before BIZOMAT went live
                                   there, and its routes back to kevos.com alone; asks before it changes anything

  secrets never shows the token or keeps it: it is typed at a hidden prompt, checked with Cloudflare and passed
  straight to Fly, so it is not on screen, in PowerShell's history or in a file.

  move cad, back cad, retire cados and delete cados run gocore-website's infrastructure/migrate/cad/to-fly.mjs, which
  prints names, counts and checksums only, never a setting's value. Each shows what it will do first; move and back
  ask you to type yes, retire and delete to type "release cados" and "delete cados" (they cannot be undone).

  A deploy sends exactly what GitHub holds on the repository's main branch, never local edits. The folder must be
  on that branch, have no local changes and match GitHub; an old checkout once replaced the website (8 Oct 2026).
  The script runs the repository's own checks, shows what will go live, asks you to type yes, deploys,
  checks the live addresses and adds a line to deploy-log.csv. Add -DryRun to do everything but the deploy.

.PARAMETER DryRun
  Run every check and stop before deploying.

.PARAMETER SkipChecks
  Deploy without running the repository's checks (and, for cad, without passing GitHub checks). Not recommended.

.PARAMETER ApplyMigrations
  tasks only: apply waiting database migrations to the live database. Normally there are none.

.PARAMETER Force
  move cad only: the cad group's volume already holds CAD data (an earlier attempt); replace it (it is kept in
  /data/backups on that volume).
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)] [ValidateSet('setup', 'status', 'deploy', 'secrets', 'sync', 'move', 'back', 'retire', 'delete', 'restore', 'help')] [string] $Command = 'help',
    [Parameter(Position = 1)] [ValidateSet('website', 'cad', 'tasks', 'kevos', 'cados')] [string] $App = '',
    [switch] $DryRun,
    [switch] $SkipChecks,
    [switch] $ApplyMigrations,
    [switch] $Force
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = $PSScriptRoot
$Owner = 'jogkev-creator'
$Repos = @('gocore-website', 'CADOS', 'PMO')
$IsWin = ($env:OS -eq 'Windows_NT')
$Curl = if ($IsWin) { 'curl.exe' } else { 'curl' }
$NullDevice = if ($IsWin) { 'NUL' } else { '/dev/null' }

# ----------------------------------------------------------------------------- helpers

function Write-Title([string] $Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }

function Stop-Here([string] $Text) {
    Write-Host ''
    Write-Host "STOP: $Text" -ForegroundColor Red
    exit 1
}

function Invoke-Step {
    # Runs a program with its output on screen; stops the script if it fails.
    param([string] $Exe, [string[]] $Arguments, [string] $In = $Root)
    Write-Host "> $Exe $($Arguments -join ' ')" -ForegroundColor DarkGray
    Push-Location -LiteralPath $In
    try { & $Exe @Arguments; $code = $LASTEXITCODE } finally { Pop-Location }
    if ($code -ne 0) { Stop-Here "$Exe $($Arguments -join ' ') failed (exit code $code)." }
}

function Get-Output {
    # A program's output as text, or $null if it fails. Its error output is not shown.
    param([string] $Exe, [string[]] $Arguments, [string] $In = $Root)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location -LiteralPath $In
    try { $out = & $Exe @Arguments 2>$null; $code = $LASTEXITCODE } finally { Pop-Location; $ErrorActionPreference = $saved }
    if ($code -ne 0) { return $null }
    return (($out | Out-String).Trim())
}

function Test-Exit {
    # $true when the program exits with 0.
    param([string] $Exe, [string[]] $Arguments, [string] $In = $Root)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location -LiteralPath $In
    try { & $Exe @Arguments 2>$null | Out-Null; $ok = ($LASTEXITCODE -eq 0) } finally { Pop-Location; $ErrorActionPreference = $saved }
    return $ok
}

function Test-Tool([string] $Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function Assert-Tool([string] $Name, [string] $Hint) {
    if (-not (Test-Tool $Name)) { Stop-Here "$Name is not installed. $Hint" }
}

function Assert-Node {
    Assert-Tool 'node' 'Install Node.js 22 LTS (22.19 or newer) from https://nodejs.org, then open a new PowerShell window.'
    Assert-Tool 'npm' 'npm comes with Node.js: reinstall Node.js 22 LTS from https://nodejs.org.'
    $v = (Get-Output 'node' @('--version')) -replace '^v', ''
    if (-not $v -or [version]$v -lt [version]'22.19.0') { Stop-Here "Node.js $v is too old: the website needs 22.19 or newer (https://nodejs.org)." }
}

function Get-Code {
    # The HTTP status of one request, without following redirects (0 when there is no answer).
    param([string] $Url, [string] $Method = 'GET', [string] $Json = '')
    $a = @('-s', '-o', $NullDevice, '-w', '%{http_code}', '-m', '30', '-A', 'bizomat-local', '-X', $Method)
    $tmp = $null
    if ($Json) {
        $tmp = [IO.Path]::GetTempFileName()
        [IO.File]::WriteAllText($tmp, $Json)
        $a += @('-H', 'Content-Type: application/json', '--data-binary', "@$tmp")
    }
    $code = Get-Output $Curl ($a + @($Url))
    if ($tmp) { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue }
    if ($code -match '^\d+$') { return [int]$code }
    return 0
}

function Get-Body([string] $Url) {
    $b = Get-Output $Curl @('-s', '-m', '30', '-A', 'bizomat-local', $Url)
    if ($b) { return $b }
    return ''
}

function Get-Title([string] $Url) {
    # The page's <title> after redirects, or what answered instead.
    $b = Get-Output $Curl @('-s', '-L', '-m', '30', '-A', 'bizomat-local', $Url)
    if ($b -and ($b -match '<title>([^<]*)</title>')) { return $Matches[1].Trim() }
    return 'no page'
}

function Get-Json([string] $Url) {
    try { return Invoke-RestMethod -UseBasicParsing -TimeoutSec 30 -Uri $Url -Headers @{ 'User-Agent' = 'bizomat-local' } }
    catch { return $null }
}

function Get-Checks {
    # GitHub's checks on one commit: passed, failed, running, none, or unknown (no answer, or a private repository).
    param([string] $Repo, [string] $Sha)
    try {
        $r = Invoke-RestMethod -UseBasicParsing -TimeoutSec 30 -Uri "https://api.github.com/repos/$Owner/$Repo/commits/$Sha/check-runs?per_page=100" `
            -Headers @{ 'User-Agent' = 'bizomat-local'; 'Accept' = 'application/vnd.github+json' }
    } catch { return 'unknown' }
    $runs = @($r.check_runs)
    if ($runs.Count -eq 0) { return 'none' }
    if (@($runs | Where-Object { $_.status -ne 'completed' }).Count -gt 0) { return 'running' }
    $bad = @('failure', 'timed_out', 'cancelled', 'action_required', 'startup_failure')
    if (@($runs | Where-Object { $bad -contains $_.conclusion }).Count -gt 0) { return 'failed' }
    return 'passed'
}

function Get-DefaultBranch([string] $Dir) {
    # The branch GitHub shows first (main; for PMO its default branch). Asked from GitHub each time.
    if (-not (Test-Exit 'git' @('remote', 'set-head', 'origin', '--auto') $Dir)) { Stop-Here "GitHub did not say which branch is $Dir's default." }
    $ref = Get-Output 'git' @('symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD') $Dir
    if (-not $ref) { Stop-Here "Cannot tell the default branch of $Dir." }
    return ($ref -replace '^origin/', '')
}

function Get-DeployCommit([string] $Repo) {
    # The commit to deploy: the folder must be on the default branch, clean, and equal to GitHub (a folder that is
    # only behind is brought up to date; one with commits GitHub does not have is refused).
    $dir = Join-Path $Root $Repo
    if (-not (Test-Path -LiteralPath (Join-Path $dir '.git'))) { Stop-Here "$Repo is not in $Root. Run: .\bizomat.ps1 setup" }
    Invoke-Step 'git' @('fetch', '--prune', '--quiet', 'origin') $dir
    $branch = Get-DefaultBranch $dir
    $here = Get-Output 'git' @('rev-parse', '--abbrev-ref', 'HEAD') $dir
    if ($here -ne $branch) { Stop-Here "$Repo is on '$here'. Deploys come only from '$branch'. Switch with: git -C `"$dir`" switch $branch" }
    $changes = Get-Output 'git' @('status', '--porcelain') $dir
    if ($changes) { Stop-Here "$Repo has local changes, and a deploy must match GitHub exactly. Put them on GitHub through a pull request, or undo them:`n$changes" }
    $head = Get-Output 'git' @('rev-parse', 'HEAD') $dir
    $remote = Get-Output 'git' @('rev-parse', "origin/$branch") $dir
    if ($head -ne $remote) {
        if (Test-Exit 'git' @('merge-base', '--is-ancestor', 'HEAD', "origin/$branch") $dir) {
            Write-Host "Bringing $Repo up to GitHub's $branch ..."
            Invoke-Step 'git' @('merge', '--ff-only', '--quiet', "origin/$branch") $dir
            $head = $remote
        } else {
            Stop-Here "$Repo has commits that GitHub does not have. Put them on GitHub through a pull request first: a deploy only sends what GitHub holds."
        }
    }
    $subject = Get-Output 'git' @('log', '-1', '--format=%s', 'HEAD') $dir
    $when = Get-Output 'git' @('log', '-1', '--format=%cd', '--date=format:%Y-%m-%d %H:%M', 'HEAD') $dir
    return @{ Repo = $Repo; Dir = $dir; Branch = $branch; Commit = $head; Short = $head.Substring(0, 7); Subject = $subject; When = $when }
}

function Show-Commit($C) {
    Write-Host "Will deploy $($C.Repo) $($C.Branch) at $($C.Short) ($($C.When)): $($C.Subject)" -ForegroundColor White
}

function Confirm-Deploy([string] $What) {
    if ($DryRun) { Write-Host 'Dry run: every check is done; stopping before the deploy.' -ForegroundColor Yellow; return $false }
    Write-Host ''
    $typed = Read-Host "Deploy $What now? Type yes to deploy (anything else stops)"
    if ("$typed".Trim() -ne 'yes') { Write-Host 'Stopped. Nothing was deployed.'; exit 0 }
    return $true
}

function Invoke-Checks($Checks) {
    # Each check: @{ What = '...'; Test = { $true/$false }; Info = $true when it only informs }. $true if all hard ones pass.
    $all = $true
    foreach ($c in $Checks) {
        $ok = $false
        try { $ok = [bool](& $c.Test) } catch { $ok = $false }
        $info = $c.ContainsKey('Info') -and $c.Info
        if ($ok) { Write-Host "  ok    $($c.What)" -ForegroundColor Green }
        elseif ($info) { Write-Host "  note  $($c.What): not yet" -ForegroundColor Yellow }
        else { Write-Host "  FAIL  $($c.What)" -ForegroundColor Red; $all = $false }
    }
    return $all
}

function Wait-Until([scriptblock] $Test, [int] $Seconds) {
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        try { if (& $Test) { return $true } } catch { }
        Start-Sleep -Seconds 5
    }
    return $false
}

function Write-DeployLog([string] $App, $C, [string] $Result) {
    $who = $env:USERNAME
    if (-not $who) { $who = $env:USER }
    [pscustomobject]@{
        When = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'); App = $App; Repository = $C.Repo; Commit = $C.Short
        Subject = $C.Subject; Result = $Result; By = $who
    } | Export-Csv -LiteralPath (Join-Path $Root 'deploy-log.csv') -Append -NoTypeInformation -Encoding UTF8
}

# ----------------------------------------------------------------------------- CAD Automation in the Fly app bizomat

function Get-Prop($Obj, [string] $Name) {
    # A property of an object read from JSON, or $null when it has none (strict mode refuses a missing one).
    if ($null -eq $Obj) { return $null }
    $p = $Obj.PSObject.Properties[$Name]
    if ($p) { return $p.Value }
    return $null
}

function Get-TomlValue([string] $File, [string] $Name) {
    # A quoted value of fly.website.toml ('' when the line is not there).
    $m = Select-String -LiteralPath $File -Pattern ('^\s*' + [regex]::Escape($Name) + '\s*=\s*"([^"]*)"') | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value }
    return ''
}

function Get-CadTool([string] $SiteDir) {
    $tool = Join-Path $SiteDir 'infrastructure\migrate\cad\to-fly.mjs'
    if (-not (Test-Path -LiteralPath $tool)) { Stop-Here 'gocore-website has no CAD move tool yet (infrastructure/migrate/cad/to-fly.mjs): it comes with the cad group change, once that is on GitHub.' }
    return $tool
}

function Get-CadState([string] $SiteDir) {
    # Where the router sends bizomat.ai/cad and how both sides are, from the CAD move tool (read only); $null when it
    # cannot tell (no tool yet, not signed in to Fly).
    $tool = Join-Path $SiteDir 'infrastructure\migrate\cad\to-fly.mjs'
    if (-not (Test-Path -LiteralPath $tool)) { return $null }
    $raw = Get-Output 'node' @($tool, 'status', '--json') $SiteDir
    if (-not $raw) { return $null }
    $line = @($raw -split "`r?`n" | Where-Object { $_ -match '^\{' } | Select-Object -Last 1)
    if ($line.Count -eq 0) { return $null }
    try { return ($line[0] | ConvertFrom-Json) } catch { return $null }
}

function Get-CadPin([string] $SiteDir) {
    # The CADOS commit apps/cad is a copy of (apps/cad-source.json), or $null.
    $file = Join-Path $SiteDir 'apps\cad-source.json'
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    try { return (Get-Content -Raw -LiteralPath $file | ConvertFrom-Json) } catch { return $null }
}

function Assert-CadRoute([string] $SiteDir) {
    # bizomat.ai/cad goes where the running router sends it (move cad and back cad change that); fly.website.toml must
    # say the same, or a deploy would move CAD Automation away from its data.
    $toml = Join-Path $SiteDir 'fly.website.toml'
    $want = Get-TomlValue $toml 'UPSTREAM_CAD'
    if (-not $want) { return }
    $state = Get-CadState $SiteDir
    if ($null -eq $state) {
        Write-Host '  note  could not ask Fly where the router sends bizomat.ai/cad; fly.website.toml decides' -ForegroundColor Yellow
        return
    }
    $route = "$(Get-Prop $state 'route')"
    if ($route -eq 'none') { return }   # no router yet: the first deploy
    $live = (@(Get-Prop $state 'upstream') | ForEach-Object { "$_" }) -join ' | '
    $old = "$(Get-Prop $state 'old_url')"
    $new = "$(Get-Prop $state 'new_url')"
    if ($live -eq $want) { Write-Host "  ok    bizomat.ai/cad stays where it is ($want)" -ForegroundColor Green; return }
    if ($live -eq $new -and $want -eq $old) {
        Stop-Here "CAD Automation runs in the cad group (since move cad), but fly.website.toml still sends bizomat.ai/cad to cados: this deploy would send it back to the old copy of its data. Merge the gocore-website change that sets UPSTREAM_CAD = `"$new`" first. (To go back to cados on purpose: .\bizomat.ps1 back cad.)"
    }
    if ($live -eq $old -and $want -eq $new) {
        Stop-Here "fly.website.toml sends bizomat.ai/cad to the cad group, but CAD Automation's data is still on cados (or was taken back): this deploy would show its holding page to everyone. Run .\bizomat.ps1 move cad first (it switches the router itself), or set UPSTREAM_CAD back to `"$old`"."
    }
    Stop-Here "The router sends bizomat.ai/cad to $live and fly.website.toml says $want. Put them in step before deploying."
}

function Get-CadGroups([string] $SiteDir, $State) {
    # Which process groups a deploy of the Fly app bizomat updates. The cad group restarts (about a minute without CAD
    # Automation) only when it is new or its code or scripts changed since the commit it runs (its image is tagged
    # bizomat-<commit> by these deploys).
    $toml = Join-Path $SiteDir 'fly.website.toml'
    if (-not (Select-String -LiteralPath $toml -Pattern '^\s*cad\s*=' -Quiet)) { return 'proxy,web,work' }
    $cad = Get-Prop $State 'cad'
    if ($null -eq $cad) { Write-Host 'CAD Automation: its group is new, so this deploy makes it (it waits for its data until move cad).'; return 'proxy,web,work,cad' }
    $tag = "$(Get-Prop $cad 'image')"
    if ($tag -notmatch '^bizomat-([0-9a-f]{7,40})$') { Write-Host 'CAD Automation restarts with this deploy (about a minute): its image does not say which commit it runs.'; return 'proxy,web,work,cad' }
    $ran = $Matches[1]
    if (-not (Test-Exit 'git' @('cat-file', '-e', "$ran^{commit}") $SiteDir)) { Write-Host "CAD Automation restarts with this deploy (about a minute): its commit $ran is not in this folder."; return 'proxy,web,work,cad' }
    $changed = Get-Output 'git' @('diff', '--name-only', $ran, 'HEAD', '--', 'apps/cad', 'apps/cad-source.json', 'infrastructure/fly', 'infrastructure/migrate') $SiteDir
    if (-not $changed) { Write-Host "CAD Automation is not restarted: its code and scripts are as in $ran, which the cad group runs."; return 'proxy,web,work' }
    $n = @($changed -split "`r?`n").Count
    Write-Host "CAD Automation restarts with this deploy (about a minute): $n of its files changed since $ran."
    return 'proxy,web,work,cad'
}

function Get-LatestMove {
    # The newest moves\cad-* folder holding a finished move (move.json), or ''.
    $base = Join-Path $Root 'moves'
    if (-not (Test-Path -LiteralPath $base)) { return '' }
    $found = @(Get-ChildItem -LiteralPath $base -Directory -Filter 'cad-*' | Sort-Object Name -Descending | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'move.json') })
    if ($found.Count -eq 0) { return '' }
    return $found[0].FullName
}

# ----------------------------------------------------------------------------- setup and status

function Invoke-Setup {
    Write-Title "Setting up $Root"
    Assert-Tool 'git' 'Install Git for Windows from https://git-scm.com/download/win, then open a new PowerShell window.'
    Assert-Node
    if (-not (Test-Tool 'fly')) { Write-Host '  note  flyctl is not installed (needed for: deploy cad). Install: iwr https://fly.io/install.ps1 -useb | iex' -ForegroundColor Yellow }
    foreach ($r in $Repos) {
        $dir = Join-Path $Root $r
        if (Test-Path -LiteralPath (Join-Path $dir '.git')) {
            Write-Host "$r is here; fetching GitHub's latest."
            Invoke-Step 'git' @('config', 'core.autocrlf', 'false') $dir
            Invoke-Step 'git' @('fetch', '--prune', '--quiet', 'origin') $dir
        } elseif (Test-Path -LiteralPath $dir) {
            Stop-Here "$dir exists but is not a clone of $Owner/$r. Move it elsewhere first."
        } else {
            # core.autocrlf=false: files stay exactly as on GitHub (Windows line endings break the CAD image build)
            Invoke-Step 'git' @('clone', '--config', 'core.autocrlf=false', "https://github.com/$Owner/$r.git", $r) $Root
        }
    }
    foreach ($r in @('gocore-website', 'PMO')) { Invoke-Step 'npm' @('ci', '--no-audit', '--no-fund') (Join-Path $Root $r) }
    Write-Title 'Next, once on this computer'
    Write-Host '  1. Fly.io (for CAD Automation):     fly auth login'
    Write-Host "  2. Cloudflare (website and tasks):  cd `"$(Join-Path $Root 'gocore-website')`"; npx wrangler login"
    Write-Host '  3. Check:                           .\bizomat.ps1 status'
}

function Show-Status {
    Write-Title "Folders in $Root"
    foreach ($r in $Repos) {
        $dir = Join-Path $Root $r
        if (-not (Test-Path -LiteralPath (Join-Path $dir '.git'))) { Write-Host "  $r : not set up (run .\bizomat.ps1 setup)" -ForegroundColor Yellow; continue }
        [void](Test-Exit 'git' @('fetch', '--prune', '--quiet', 'origin') $dir)
        $branch = Get-DefaultBranch $dir
        $here = Get-Output 'git' @('rev-parse', '--abbrev-ref', 'HEAD') $dir
        $short = Get-Output 'git' @('rev-parse', '--short=7', 'HEAD') $dir
        $counts = (Get-Output 'git' @('rev-list', '--left-right', '--count', "HEAD...origin/$branch") $dir) -split '\s+'
        $dirty = if (Get-Output 'git' @('status', '--porcelain') $dir) { ', local changes' } else { '' }
        $remoteSha = Get-Output 'git' @('rev-parse', "origin/$branch") $dir
        $checks = Get-Checks $r $remoteSha
        Write-Host ("  {0,-15} on {1} at {2}; {3} ahead, {4} behind GitHub's {5}{6}; GitHub's checks there: {7}" -f $r, $here, $short, $counts[0], $counts[1], $branch, $dirty, $checks)
    }
    Write-Title 'Live'
    $cad = Get-Json 'https://bizomat.ai/cad/healthz'
    $cadVersion = 'no answer'
    if ($cad -and (Get-Prop $cad 'ok')) { $cadVersion = "version $(Get-Prop $cad 'version')" }
    elseif ($cad) { $cadVersion = "not serving ($(Get-Prop $cad 'status'))" }
    $cadWhere = 'ask Fly for where it runs: fly auth login'
    $cadState = Get-CadState (Join-Path $Root 'gocore-website')
    if ($cadState) {
        $route = "$(Get-Prop $cadState 'route')"
        $cadWhere = 'served by ' + $(if ($route -eq 'new') { 'the cad group of the Fly app bizomat' } elseif ($route -eq 'old') { 'the Fly app cados' } else { "nothing clear ($route)" })
    }
    $tasks = Get-Json 'https://work.kevos.com/api/health'
    $tasksState = if ($tasks) { "$($tasks.status), database $($tasks.db)" } else { 'no answer' }
    $site = Get-Title 'https://kevos.com/'
    $biz = Get-Title 'https://bizomat.ai/'
    Write-Host "  kevos.com          $site"
    Write-Host "  bizomat.ai         $biz"
    $router = Get-Json 'https://bizomat.fly.dev/__proxy/health'
    $routerState = if ($router) { "version $($router.version)" } else { 'not deployed yet' }
    Write-Host "  bizomat (Fly)      $routerState (bizomat.fly.dev/__proxy/health)"
    Write-Host "  CAD Automation     $cadVersion (bizomat.ai/cad/healthz), $cadWhere"
    if ($cadState) {
        $old = Get-Prop $cadState 'old'
        $grp = Get-Prop $cadState 'cad'
        if ($grp) { Write-Host "  cad group (Fly)    Machine $(Get-Prop $grp 'machine'), $(Get-Prop $grp 'state'), $(Get-Prop $grp 'region')" }
        if ($old) {
            $auto = if (Get-Prop $old 'autostart') { '' } else { ', does not start by itself' }
            Write-Host "  cados (Fly)        Machine $(Get-Prop $old 'machine'), $(Get-Prop $old 'state'), $(Get-Prop $old 'region')$auto"
        } else { Write-Host '  cados (Fly)        no app' }
    }
    Write-Host "  Project Management $tasksState (work.kevos.com/api/health)"
}

# ----------------------------------------------------------------------------- deploys

function Test-WorkReady {
    # The router's view of Project Management: /__proxy/ready lists each backend's health.
    $b = Get-Body 'https://bizomat.fly.dev/__proxy/ready'
    try { return [bool](($b | ConvertFrom-Json).upstreams.work.ok) } catch { return $false }
}

function New-PlatformVolumes([string] $Dir) {
    # fly deploy does not create the volume of a group added to an existing app: work_data and cad_data, 3 GB in
    # Sydney, a snapshot every day kept 30 days.
    $toml = Join-Path $Dir 'fly.website.toml'
    $vols = Get-Output 'fly' @('volumes', 'list', '--app', 'bizomat', '--json') $Dir
    foreach ($v in @(@{ Name = 'work_data'; What = 'Project Management''s data' }, @{ Name = 'cad_data'; What = 'CAD Automation''s data' })) {
        if (-not (Select-String -LiteralPath $toml -Pattern ('source\s*=\s*"' + $v.Name + '"') -Quiet)) { continue }
        if ("$vols" -match ('"' + $v.Name + '"')) { continue }
        Write-Host "Creating the volume for $($v.What) ($($v.Name): 3 GB in Sydney, a snapshot every day kept 30 days)." -ForegroundColor Yellow
        Invoke-Step 'fly' @('volumes', 'create', $v.Name, '--region', 'syd', '--size', '3', '--snapshot-retention', '30', '--app', 'bizomat', '--yes') $Dir
    }
}

function Deploy-Website {
    Write-Title 'The Fly app bizomat: the website, the router behind bizomat.ai, Project Management, CAD Automation''s group'
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    Assert-Node
    $c = Get-DeployCommit 'gocore-website'
    Show-Commit $c
    $toml = Join-Path $c.Dir 'fly.website.toml'
    if (-not (Test-Path -LiteralPath $toml)) { Stop-Here 'gocore-website has no fly.website.toml yet: the website moves to Fly once that change is on GitHub.' }
    $hasCad = Select-String -LiteralPath $toml -Pattern '^\s*cad\s*=' -Quiet
    if (-not $SkipChecks) {
        Invoke-Step 'npm' @('ci', '--no-audit', '--no-fund') $c.Dir
        Invoke-Step 'npm' @('run', 'verify') $c.Dir                                       # the site: types, tests, build, page checks
        Invoke-Step 'node' @('--test', 'infrastructure/proxy/test/*.test.mjs') $c.Dir     # the router
    }
    if ($hasCad) {
        # the cad group is built from apps/cad: it must be exactly the CADOS commit it names (CADOS is what runs)
        Invoke-Step 'node' @('scripts/sync-cad.mjs', 'check', '--cados', (Join-Path $Root 'CADOS')) $c.Dir
    }
    $exists = Test-Exit 'fly' @('status', '--app', 'bizomat') $c.Dir
    $groups = 'proxy,web,work'
    if ($hasCad) { $groups = 'proxy,web,work,cad' }
    if (-not $exists) {
        Write-Host ''
        Write-Host 'The Fly app bizomat does not exist yet. Creating it costs nothing until it runs.' -ForegroundColor Yellow
    } elseif ($hasCad) {
        Assert-CadRoute $c.Dir
        $state = Get-CadState $c.Dir
        if ($state) { $groups = Get-CadGroups $c.Dir $state }
        else { Write-Host 'CAD Automation restarts with this deploy (about a minute): could not ask Fly which commit its group runs.' }
    }
    if (-not (Confirm-Deploy 'the Fly app bizomat (the website and the router; Project Management and CAD Automation as above)')) { return }
    if (-not $exists) {
        Invoke-Step 'fly' @('apps', 'create', 'bizomat') $c.Dir
        Invoke-Step 'fly' @('ips', 'allocate-v6', '--app', 'bizomat') $c.Dir
        Invoke-Step 'fly' @('ips', 'allocate-v4', '--shared', '--app', 'bizomat') $c.Dir
    }
    New-PlatformVolumes $c.Dir
    # Built on Fly's machines; one Machine per group; the commit as its version and as the image's tag (so the next
    # deploy can tell what the cad group runs).
    $deployArgs = @('deploy', '--config', 'fly.website.toml', '--app', 'bizomat', '--remote-only', '--ha=false', '--image-label', "bizomat-$($c.Short)", '--build-arg', "BIZOMAT_VERSION=$($c.Short)")
    # every group: flyctl's default (it also makes a group's first Machine); a subset only to leave cad running
    $allGroups = if ($hasCad) { 'proxy,web,work,cad' } else { 'proxy,web,work' }
    if ($groups -ne $allGroups) { $deployArgs += @('--process-groups', $groups) }
    Invoke-Step 'fly' $deployArgs $c.Dir
    # bizomat.ai points at this app; bizomat.fly.dev answers its own health endpoints and sends everything else to
    # bizomat.ai. A backend can need a moment after the router restarts, so those checks wait up to 90 s.
    Write-Title 'Live checks (bizomat.ai)'
    $want = $c.Short
    [void](Wait-Until { (Get-Json 'https://bizomat.fly.dev/__proxy/health').version -eq $want } 180)
    $checks = @(
        @{ What = "the router runs $want (bizomat.fly.dev/__proxy/health)"; Test = { (Get-Json 'https://bizomat.fly.dev/__proxy/health').version -eq $want } },
        @{ What = 'the website answers (bizomat.ai)'; Test = { Wait-Until { (Get-Title 'https://bizomat.ai/') -match 'BIZOMAT' } 90 } },
        @{ What = 'its APIs answer (/api/chat, no AI call made)'; Test = { Wait-Until { (Get-Code 'https://bizomat.ai/api/chat' 'POST' '{}') -eq 422 } 90 } },
        @{ What = 'CAD Automation answers (bizomat.ai/cad/)'; Test = { Wait-Until { (Get-Code 'https://bizomat.ai/cad/') -eq 200 } 90 } },
        @{ What = '/tasks/ answers (Project Management, or 302 to work.kevos.com before its switch)'; Test = { Wait-Until { $t = Get-Code 'https://bizomat.ai/tasks/'; ($t -eq 200) -or ($t -eq 302) } 90 } }
    )
    # Project Management on Fly, once fly.website.toml runs it (the work group)
    if (Select-String -LiteralPath $toml -Pattern '^\s*work\s*=' -Quiet) {
        $checks += @{ What = 'Project Management runs on Fly (the router reports work healthy)'; Test = { Wait-Until { Test-WorkReady } 90 } }
    }
    if ($hasCad) {
        $siteDir = $c.Dir
        $checks += @{ What = 'the cad group runs (its holding page until move cad, then the CAD server)'; Test = { Wait-Until { $s = Get-CadState $siteDir; $g = Get-Prop $s 'cad'; ($null -ne $g) -and ("$(Get-Prop $g 'state')" -eq 'started') } 120 } }
    }
    $checks += @{ What = 'bizomat.ai/login goes to the sign-in page'; Info = $true; Test = { (Get-Code 'https://bizomat.ai/login') -eq 301 } }
    $checks += @{ What = 'bizomat.fly.dev sends people to bizomat.ai'; Info = $true; Test = { (Get-Code 'https://bizomat.fly.dev/') -eq 301 } }
    $ok = Invoke-Checks $checks
    $result = if ($ok) { 'ok' } else { 'deployed; live checks failed' }
    Write-DeployLog 'website' $c $result
    if (-not $ok) { Stop-Here 'A live check failed. Logs: fly logs -a bizomat. To go back: fly releases -a bizomat --image, then fly deploy --config fly.website.toml -a bizomat --image <the previous image> --ha=false.' }
    Write-Host 'Done.' -ForegroundColor Green
}

function Deploy-Cad {
    # After move cad, CAD Automation is the cad group of the Fly app bizomat; before it, the Fly app cados.
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    $site = Get-DeployCommit 'gocore-website'
    $state = Get-CadState $site.Dir
    if ($state -and ("$(Get-Prop $state 'route')" -eq 'new')) { Deploy-CadGroup $site; return }
    if ($state -and ("$(Get-Prop $state 'route')" -ne 'old') -and ("$(Get-Prop $state 'route')" -ne 'none')) {
        Stop-Here "The router sends bizomat.ai/cad to neither cados nor the cad group ($(Get-Prop $state 'route')): look at .\bizomat.ps1 status first."
    }
    Deploy-Cados
}

function Deploy-CadGroup($Site) {
    Write-Title 'CAD Automation: the cad group of the Fly app bizomat (bizomat.ai/cad)'
    Assert-Node
    $cados = Get-DeployCommit 'CADOS'
    Show-Commit $cados
    $checks = Get-Checks 'CADOS' $cados.Commit
    Write-Host "GitHub's checks on CADOS $($cados.Short): $checks"
    if ($checks -ne 'passed' -and -not $SkipChecks) {
        Stop-Here "CAD Automation's tests run on GitHub (they need the CAD libraries and SOLIDWORKS stand-ins). Deploy once they pass."
    }
    $pin = Get-CadPin $Site.Dir
    $pinned = "$(Get-Prop $pin 'commit')"
    if ($pinned -ne $cados.Commit) {
        $p = if ($pinned.Length -ge 7) { $pinned.Substring(0, 7) } else { 'nothing' }
        Stop-Here "The cad group is built from gocore-website's apps/cad, which is CADOS $p; CADOS main is $($cados.Short). Bring it across first: .\bizomat.ps1 sync cad (a branch to merge on GitHub), then run this again."
    }
    Invoke-Step 'node' @('scripts/sync-cad.mjs', 'check', '--cados', $cados.Dir) $Site.Dir
    Assert-CadRoute $Site.Dir
    $keys = Get-Json 'https://bizomat.ai/cad/v2/keys'
    $kid = "$(Get-Prop (@(Get-Prop $keys 'keys') | Select-Object -First 1) 'kid')"
    Show-Commit $Site
    if (-not (Confirm-Deploy "CAD Automation, CADOS $($cados.Short), to the cad group (about a minute off line)")) { return }
    Invoke-Step 'fly' @('deploy', '--config', 'fly.website.toml', '--app', 'bizomat', '--remote-only', '--ha=false', '--process-groups', 'cad', '--image-label', "bizomat-$($Site.Short)", '--build-arg', "BIZOMAT_VERSION=$($Site.Short)") $Site.Dir
    Write-Title 'Live checks (bizomat.ai/cad)'
    $want = $cados.Short
    [void](Wait-Until { "$(Get-Prop (Get-Json 'https://bizomat.ai/cad/healthz') 'version')" -eq $want } 240)
    $ok = Invoke-Checks @(
        @{ What = "bizomat.ai/cad runs CADOS $want"; Test = { $h = Get-Json 'https://bizomat.ai/cad/healthz'; [bool](Get-Prop $h 'ok') -and ("$(Get-Prop $h 'version')" -eq $want) } },
        @{ What = 'the same signing key (paired computers keep trusting it: /cad/v2/keys)'; Test = { $k = Get-Json 'https://bizomat.ai/cad/v2/keys'; $kid -and ("$(Get-Prop (@(Get-Prop $k 'keys') | Select-Object -First 1) 'kid')" -eq $kid) } },
        @{ What = 'accounts are there: setup is closed (/cad/setup goes to sign-in)'; Test = { (Get-Code 'https://bizomat.ai/cad/setup') -eq 303 } },
        @{ What = 'AI apps: /cad/mcp asks for sign-in (401)'; Test = { (Get-Code 'https://bizomat.ai/cad/mcp' 'POST' '{}') -eq 401 } }
    )
    $result = if ($ok) { 'ok' } else { 'deployed; live checks failed' }
    Write-DeployLog 'cad' $cados $result
    if (-not $ok) { Stop-Here 'A live check failed. Logs: fly logs -a bizomat. To go back: fly releases -a bizomat --image, then in gocore-website: fly deploy --config fly.website.toml -a bizomat --image <the previous image> --process-groups cad --ha=false.' }
    Write-Host 'Done.' -ForegroundColor Green
}

function Deploy-Cados {
    Write-Title 'CAD Automation: Fly app cados (bizomat.ai/cad, until move cad)'
    $c = Get-DeployCommit 'CADOS'
    Show-Commit $c
    $checks = Get-Checks 'CADOS' $c.Commit
    Write-Host "GitHub's checks on $($c.Short): $checks"
    if ($checks -ne 'passed' -and -not $SkipChecks) {
        Stop-Here "CAD Automation's tests run on GitHub (they need the CAD libraries and SOLIDWORKS stand-ins). Deploy once they pass."
    }
    # move cad stops cados and turns its autostart off: a deploy would start the old copy of the data again
    $machines = Get-Output 'fly' @('machines', 'list', '--app', 'cados', '--json') $c.Dir
    if ($machines) {
        # ConvertFrom-JsonList: Windows PowerShell 5.1's ConvertFrom-Json would hand the list on as one object
        $list = ConvertFrom-JsonList $machines
        if ($null -eq $list) { $list = @() }
        foreach ($m in $list) {
            $svc = @(Get-Prop (Get-Prop $m 'config') 'services')
            if (@($svc | Where-Object { $null -ne $_ -and (Get-Prop $_ 'autostart') -eq $false }).Count -gt 0) {
                Stop-Here 'cados was stopped by move cad (it does not start by itself): CAD Automation runs in the cad group of the Fly app bizomat. Bring gocore-website up to date and run .\bizomat.ps1 deploy cad again; to use cados again on purpose: .\bizomat.ps1 back cad.'
            }
        }
    }
    if (-not (Confirm-Deploy 'CAD Automation (bizomat.ai/cad)')) { return }
    # The same command GitHub's deploy workflow uses: built on Fly's machines, one Machine, the commit as its version.
    Invoke-Step 'fly' @('deploy', '--app', 'cados', '--remote-only', '--ha=false', '--build-arg', "OPENSKETCH_VERSION=$($c.Short)", '--env', 'OPENSKETCH_PUBLIC_URL=https://bizomat.ai/cad') $c.Dir
    Write-Title 'Live checks'
    $want = $c.Short
    [void](Wait-Until { (Get-Json 'https://cados.fly.dev/healthz').version -eq $want } 180)
    $ok = Invoke-Checks @(
        @{ What = "the CAD app runs $want (cados.fly.dev/healthz)"; Test = { (Get-Json 'https://cados.fly.dev/healthz').version -eq $want } },
        @{ What = 'bizomat.ai/cad/ answers'; Test = { (Get-Code 'https://bizomat.ai/cad/') -eq 200 } },
        @{ What = 'the old address sends pages to bizomat.ai/cad (cados.kevos.com/docs: 301)'; Test = { (Get-Code 'https://cados.kevos.com/docs') -eq 301 } },
        @{ What = 'connectors made with cados.kevos.com keep their address'; Test = { (Get-Json 'https://cados.kevos.com/.well-known/oauth-protected-resource/mcp').resource -eq 'https://cados.kevos.com/mcp' } }
    )
    $result = if ($ok) { 'ok' } else { 'deployed; live checks failed' }
    Write-DeployLog 'cad' $c $result
    if (-not $ok) { Stop-Here "A live check failed. Logs: fly logs -a cados. To go back: fly releases -a cados --image, then fly deploy -a cados --image <the previous image>." }
    Write-Host 'Done.' -ForegroundColor Green
}

function Deploy-Tasks {
    Write-Title 'Project Management: Cloudflare Worker workos-platform-preview (work.kevos.com, bizomat.ai/tasks)'
    Assert-Node
    $c = Get-DeployCommit 'PMO'
    Show-Commit $c
    Write-Host "GitHub's checks on $($c.Short): $(Get-Checks 'PMO' $c.Commit)"
    if (-not $SkipChecks) {
        Invoke-Step 'npm' @('ci', '--no-audit', '--no-fund') $c.Dir
        Invoke-Step 'npm' @('run', 'check') $c.Dir   # lint, type check, tests in the Workers runtime, build
    }
    # The live database: migrations waiting to be applied (normally none). Never applied without -ApplyMigrations.
    $pending = Get-Output 'npx' @('wrangler', 'd1', 'migrations', 'list', 'DB', '--remote', '--env', 'preview') $c.Dir
    if ($null -eq $pending) { Stop-Here "Could not read the live database's migrations: not signed in (npx wrangler login), or more than one Cloudflare account (set `$env:CLOUDFLARE_ACCOUNT_ID). To see why: cd PMO; npx wrangler d1 migrations list DB --remote --env preview" }
    $waiting = $pending -notmatch 'No migrations to apply'
    if ($waiting) {
        Write-Host $pending
        if (-not $ApplyMigrations) { Stop-Here 'The live database has migrations waiting. Read them; to apply them, run again with -ApplyMigrations.' }
    }
    if (-not (Confirm-Deploy 'Project Management (work.kevos.com)')) { return }
    if ($waiting) {
        Write-Host 'Restore point of the live database before the migrations (keep the bookmark):'
        Invoke-Step 'npx' @('wrangler', 'd1', 'time-travel', 'info', 'workos-platform-preview-db', '--env', 'preview') $c.Dir
        Invoke-Step 'npx' @('wrangler', 'd1', 'migrations', 'apply', 'DB', '--remote', '--env', 'preview') $c.Dir
    }
    Invoke-Step 'npx' @('wrangler', 'deploy', '--env', 'preview', '--message', "$($c.Short) from $env:COMPUTERNAME") $c.Dir
    Write-Title 'Live checks'
    [void](Wait-Until { (Get-Json 'https://work.kevos.com/api/health').status -eq 'ok' } 120)
    Invoke-Step 'node' @('scripts/smoke.mjs', 'https://work.kevos.com') $c.Dir   # read-only: health, headers, sign-in enforcement
    $ok = Invoke-Checks @(
        @{ What = 'pages carry <base href> (this build serves both work.kevos.com and bizomat.ai/tasks)'; Test = { (Get-Body 'https://work.kevos.com/login') -match '<base href="/">' } },
        @{ What = 'bizomat.ai/tasks reaches Project Management'; Info = $true; Test = { (Get-Body 'https://bizomat.ai/tasks/login') -match '<base href="/tasks/">' } }
    )
    $result = if ($ok) { 'ok' } else { 'deployed; live checks failed' }
    Write-DeployLog 'tasks' $c $result
    if (-not $ok) { Stop-Here 'A live check failed. To go back: npx wrangler rollback --env preview (in the PMO folder).' }
    Write-Host 'Done.' -ForegroundColor Green
}

function Set-WebsiteSecrets {
    # CF_ACCOUNT_ID and CF_AI_TOKEN on the Fly app bizomat: the website's assistant and AI search use Workers AI with
    # them (without them, search runs on keywords). The token is never printed: not even in the command shown.
    Write-Title 'Workers AI for the BIZOMAT website (Fly app bizomat)'
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    if (-not (Test-Exit 'fly' @('status', '--app', 'bizomat'))) { Stop-Here 'The Fly app bizomat does not exist yet: run .\bizomat.ps1 deploy website first.' }
    Write-Host 'The account ID is on the Cloudflare dashboard (Workers & Pages, right-hand side: Account ID).'
    $account = "$(Read-Host 'Cloudflare account ID')".Trim().ToLowerInvariant()
    # The website refuses to start with a malformed ID, so it is checked here, before Fly has it.
    if ($account -notmatch '^[0-9a-f]{32}$') { Stop-Here 'That is not an account ID (32 characters, 0-9 and a-f). Nothing was changed.' }
    $secure = Read-Host 'Workers AI token (what you type or paste stays hidden; then press Enter)' -AsSecureString
    $token = (New-Object System.Net.NetworkCredential('', $secure)).Password.Trim()
    if ($token -notmatch '^[A-Za-z0-9_.-]{20,}$') { Stop-Here 'That does not look like a Cloudflare API token. Nothing was changed.' }

    Write-Host 'Checking them with Cloudflare (reads the Workers AI model list; costs nothing)...'
    $status = 0
    try {
        $r = Invoke-RestMethod -UseBasicParsing -TimeoutSec 60 -Uri "https://api.cloudflare.com/client/v4/accounts/$account/ai/models/search?per_page=1" `
            -Headers @{ Authorization = "Bearer $token"; 'User-Agent' = 'bizomat-local' }
        if ($r.success) { $status = 200 }
    } catch {
        $p = $_.Exception.PSObject.Properties['Response']
        if ($p -and $p.Value) { try { $status = [int]$p.Value.StatusCode } catch { $status = 0 } }
    }
    if ($status -ne 200) {
        if ($status -in @(400, 401, 403, 404)) { Stop-Here "Cloudflare refused them (HTTP $status): check the account ID, and that the token was made with the Workers AI template for this account. Nothing was changed." }
        Stop-Here 'Could not reach Cloudflare to check the token. Nothing was changed; try again in a minute.'
    }
    Write-Host 'Cloudflare accepted them.' -ForegroundColor Green

    Write-Host ''
    Write-Host '> fly secrets set CF_ACCOUNT_ID=<the account ID> CF_AI_TOKEN=<hidden> --app bizomat' -ForegroundColor DarkGray
    & fly secrets set "CF_ACCOUNT_ID=$account" "CF_AI_TOKEN=$token" --app bizomat
    $code = $LASTEXITCODE
    $token = $null
    if ($code -ne 0) { Stop-Here "fly secrets set failed (exit code $code)." }

    Write-Title 'Live check (bizomat.fly.dev)'
    $ai = Wait-Until {
        try {
            $d = Invoke-RestMethod -UseBasicParsing -TimeoutSec 30 -Method Post -ContentType 'application/json' `
                -Uri 'https://bizomat.fly.dev/api/discover' -Headers @{ 'User-Agent' = 'bizomat-local' } -Body '{"question":"weld strength"}'
            return ($d.ok -and $d.ai)
        } catch { return $false }
    } 180
    if ($ai) { Write-Host 'The website uses Workers AI: its assistant and AI search are on.' -ForegroundColor Green }
    else { Write-Host 'Saved on Fly, but the website does not use AI yet. Look at: fly logs --app bizomat' -ForegroundColor Yellow }
}

function Move-Tasks {
    # Project Management's data from Cloudflare (D1 and R2) to the work Machine of the Fly app bizomat, with this
    # computer's wrangler and fly sign-ins. gocore-website's apps/work/scripts/migrate/to-fly.mjs does the work:
    # prepare only reads Cloudflare; apply, after you type yes, uploads, checks and puts the data in place on Fly.
    Write-Title 'Project Management to Fly: its data from Cloudflare to the Fly app bizomat (bizomat.ai/tasks)'
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    Assert-Node
    $c = Get-DeployCommit 'gocore-website'
    Show-Commit $c
    $work = Join-Path $c.Dir 'apps\work'
    if (-not (Test-Path -LiteralPath (Join-Path $work 'scripts\migrate\to-fly.mjs'))) { Stop-Here 'gocore-website has no move tool yet (apps/work/scripts/migrate/to-fly.mjs): it comes with the Project Management on Fly change.' }
    if (-not (Test-Exit 'fly' @('status', '--app', 'bizomat'))) { Stop-Here 'The Fly app bizomat does not exist yet: run .\bizomat.ps1 deploy website first.' }
    Invoke-Step 'npm' @('ci', '--no-audit', '--no-fund') $work     # wrangler and the move's packages
    $dir = Join-Path $Root ('moves\tasks-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Write-Host ''
    Write-Host "Working folder: $dir"
    Write-Host 'It holds a copy of Project Management''s data: keep it on this computer, delete it once bizomat.ai/tasks is checked.' -ForegroundColor Yellow
    Write-Host 'If wrangler says it sees more than one Cloudflare account: $env:CLOUDFLARE_ACCOUNT_ID = ''<the account ID>'', then run this again.'
    Invoke-Step 'node' @('scripts/migrate/to-fly.mjs', 'prepare', $dir) $work
    if ($DryRun) { Write-Host 'Dry run: the copy is prepared and checked; nothing on Fly changed.' -ForegroundColor Yellow; return }
    Write-Host ''
    Write-Host 'Next: upload this copy and replace the data of Project Management on Fly with it (what is there now is kept in /data/backups).'
    Write-Host 'work.kevos.com is not changed, and bizomat.ai/tasks still sends people there until the switch.'
    $typed = Read-Host 'Put this copy on Fly now? Type yes to continue (anything else stops)'
    if ("$typed".Trim() -ne 'yes') { Write-Host 'Stopped. Nothing on Fly changed.'; return }
    Invoke-Step 'node' @('scripts/migrate/to-fly.mjs', 'apply', $dir) $work
    Write-DeployLog 'tasks-move' $c 'applied'
    Write-Title 'Next'
    Write-Host '1. Open https://bizomat.fly.dev/__preview/work, sign in with your own email and password, and compare a board,'
    Write-Host '   a document and a file with work.kevos.com. Until the switch, leave work.kevos.com unchanged.'
    Write-Host '2. https://bizomat.fly.dev/__preview/clear takes that browser back to the website.'
    Write-Host '3. Then the switch: bizomat.ai/tasks serves Project Management from Fly.'
}

# ----------------------------------------------------------------------------- CAD Automation: sync, move, back, retire

function Sync-Cad {
    # apps/cad in gocore-website is CAD Automation exactly as CADOS holds it at one commit (apps/cad-source.json): the
    # cad group is built from it. This brings CADOS main across on a branch of its own, pushed to GitHub to merge there.
    Write-Title 'apps/cad in gocore-website: CADOS main, byte for byte (a branch to merge on GitHub)'
    Assert-Node
    $cados = Get-DeployCommit 'CADOS'
    $checks = Get-Checks 'CADOS' $cados.Commit
    Write-Host "CADOS main is $($cados.Short) ($($cados.When)): $($cados.Subject); GitHub's checks there: $checks"
    if ($checks -ne 'passed' -and -not $SkipChecks) { Stop-Here 'Its checks have not passed on GitHub: bring it across once they have.' }
    $site = Get-DeployCommit 'gocore-website'
    $from = "$(Get-Prop (Get-CadPin $site.Dir) 'commit')"
    if ($from -eq $cados.Commit) { Write-Host "apps/cad is CADOS $($cados.Short) already: nothing to bring across." -ForegroundColor Green; return }
    if ($from.Length -eq 40) {
        Write-Host ''
        Write-Host "CADOS commits since apps/cad's $($from.Substring(0, 7)):"
        $log = Get-Output 'git' @('log', '--oneline', "$from..$($cados.Commit)") $cados.Dir
        if ($log) { Write-Host $log } else { Write-Host '  (not an earlier commit of CADOS main: apps/cad is replaced as a whole)' }
    }
    $branch = 'cad-sync-' + $cados.Short
    if ($DryRun) { Write-Host "Dry run: would make the branch $branch with apps/cad = CADOS $($cados.Short) and push it." -ForegroundColor Yellow; return }
    Write-Host ''
    $typed = Read-Host "Make the branch $branch in gocore-website and push it to GitHub? Type yes (anything else stops)"
    if ("$typed".Trim() -ne 'yes') { Write-Host 'Stopped. Nothing was changed.'; return }
    Invoke-Step 'git' @('switch', '-c', $branch) $site.Dir
    try {
        Invoke-Step 'node' @('scripts/sync-cad.mjs', 'to', $cados.Commit, '--cados', $cados.Dir) $site.Dir
        Invoke-Step 'git' @('commit', '-q', '-m', ('apps/cad: CADOS ' + $cados.Short + ', byte for byte'), '-m', ('CADOS main at ' + $cados.Short + ': ' + $cados.Subject)) $site.Dir
        Invoke-Step 'git' @('push', '-u', 'origin', $branch) $site.Dir
    } finally {
        [void](Test-Exit 'git' @('switch', $site.Branch) $site.Dir)
    }
    $title = [uri]::EscapeDataString('apps/cad: CADOS ' + $cados.Short + ' [skip ci]')
    Write-Host ''
    Write-Host 'Pushed. Open the pull request; its title ends with [skip ci], so merging it deploys nothing:' -ForegroundColor Green
    Write-Host ('  https://github.com/' + $Owner + '/gocore-website/compare/' + $site.Branch + '...' + $branch + '?expand=1&title=' + $title)
    Write-Host 'Merge it once its checks pass, then: .\bizomat.ps1 deploy cad'
}

function Move-Cad {
    # CAD Automation from the Fly app cados to the cad group of the Fly app bizomat, with its data; bizomat.ai/cad with it.
    # gocore-website's infrastructure/migrate/cad/to-fly.mjs does the work: check only reads (and copies the data while
    # cados runs, to prove the way); apply, after you type yes, moves it, and takes the way back by itself on a failure.
    Write-Title 'CAD Automation to the cad group of the Fly app bizomat (Sydney), with its data'
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    Assert-Node
    $c = Get-DeployCommit 'gocore-website'
    Show-Commit $c
    $tool = Get-CadTool $c.Dir
    $dir = Join-Path $Root ('moves\cad-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Write-Host ''
    Write-Host "Working folder: $dir"
    Write-Host 'It holds a copy of CAD Automation''s data with every key in it: keep it on this computer, delete it when the rollback window ends.' -ForegroundColor Yellow
    Write-Title 'Checks (nothing changes; cados keeps running)'
    Invoke-Step 'node' @($tool, 'check', $dir) $c.Dir
    if ($DryRun) { Write-Host 'Dry run: everything is checked and a copy of the data was verified here; nothing on Fly changed.' -ForegroundColor Yellow; return }
    Write-Title 'The move'
    Write-Host 'CAD Automation is off line for a few minutes: bizomat.ai/cad says it is being moved, the add-ins and the'
    Write-Host 'Companion retry by themselves, AI apps get an error until it is back. If a step fails, the move takes the way'
    Write-Host 'back by itself (cados again). Afterwards the way back is: .\bizomat.ps1 back cad'
    Write-Host 'Old addresses: cados.kevos.com and cados.fly.dev reach cados directly, so they stop answering when it stops.'
    Write-Host 'Computers with the 0.13 Companion use bizomat.ai/cad by themselves; the check above counts AI app connections'
    Write-Host 'by the address they were made with.'
    Write-Host ''
    $typed = Read-Host 'Move CAD Automation now? Type yes to continue (anything else stops)'
    if ("$typed".Trim() -ne 'yes') { Write-Host 'Stopped. Nothing on Fly changed.'; return }
    $moveArgs = @($tool, 'apply', $dir)
    if ($Force) { $moveArgs += '--force' }
    Write-Host "> node $($moveArgs -join ' ')" -ForegroundColor DarkGray
    Push-Location -LiteralPath $c.Dir
    try { & node @moveArgs; $code = $LASTEXITCODE } finally { Pop-Location }
    if ($code -ne 0) {
        Write-DeployLog 'cad-move' $c 'stopped (way back taken)'
        $h = Get-Json 'https://bizomat.ai/cad/healthz'
        $now = if ($h -and (Get-Prop $h 'ok')) { "answers (version $(Get-Prop $h 'version'))" } else { 'does not answer' }
        Stop-Here "The move stopped (the reason is above) and took the way back. bizomat.ai/cad $now. If CAD Automation stays off line: .\bizomat.ps1 back cad"
    }
    Write-DeployLog 'cad-move' $c 'moved to the cad group'
    Write-Title 'Live checks (from here, independent of the move tool)'
    $pin = "$(Get-Prop (Get-CadPin $c.Dir) 'commit')"
    $want = if ($pin.Length -ge 7) { $pin.Substring(0, 7) } else { '' }
    [void](Invoke-Checks @(
            @{ What = "bizomat.ai/cad answers from the cad group (CADOS $want)"; Test = { $h = Get-Json 'https://bizomat.ai/cad/healthz'; [bool](Get-Prop $h 'ok') -and ((-not $want) -or ("$(Get-Prop $h 'version')" -eq $want)) } },
            @{ What = 'accounts are there: setup is closed (/cad/setup goes to sign-in)'; Test = { (Get-Code 'https://bizomat.ai/cad/setup') -eq 303 } },
            @{ What = 'cados.fly.dev no longer answers (cados is stopped)'; Info = $true; Test = { (Get-Code 'https://cados.fly.dev/healthz') -ne 200 } }
        ))
    Write-Title 'Next'
    Write-Host '1. Check it yourself: sign in at https://bizomat.ai/cad/login. Admin lists the same people, Settings shows the same'
    Write-Host '   private connector address, SOLIDWORKS lists the same computers; ask your AI app to run sw_status.'
    Write-Host '2. Make the route permanent on GitHub: gocore-website''s fly.website.toml sets'
    Write-Host '   UPSTREAM_CAD = "http://cad.process.bizomat.internal:8001" (a pull request). Until it is merged, deploy website'
    Write-Host '   refuses, so nothing sends bizomat.ai/cad back to the old copy.'
    Write-Host '3. Old addresses: to keep cados.kevos.com working, move it to the Fly app bizomat (certificate, then its DNS record;'
    Write-Host '   gocore-website infrastructure/migrate/cad/README.md, "Old addresses"). cados.fly.dev cannot move.'
    Write-Host '4. Once you are sure it works: .\bizomat.ps1 retire cados (releases cados''s public addresses), and at the end of'
    Write-Host '   the rollback window .\bizomat.ps1 delete cados. Both ask you first; neither can be undone.'
    Write-Host "5. The copy in $dir holds every key of CAD Automation: delete that folder when the rollback window ends."
}

function Back-Cad {
    # The way back after move cad: cados started again with its data as it was at the move, bizomat.ai/cad to cados,
    # the cad group into maintenance (it keeps its data).
    Write-Title 'The way back: bizomat.ai/cad served by the Fly app cados again'
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    Assert-Node
    $c = Get-DeployCommit 'gocore-website'
    $tool = Get-CadTool $c.Dir
    Invoke-Step 'node' @($tool, 'status') $c.Dir
    Write-Host ''
    Write-Host 'cados starts again with its data as it was at the move. What changed in the cad group since then stays there and'
    Write-Host 'is not carried back: sign-ins, AI apps whose sign-in was renewed there (connect them again), computers paired since.'
    if ($DryRun) { Write-Host 'Dry run: nothing changed.' -ForegroundColor Yellow; return }
    Write-Host ''
    $typed = Read-Host 'Take CAD Automation back to cados now? Type yes to continue (anything else stops)'
    if ("$typed".Trim() -ne 'yes') { Write-Host 'Stopped. Nothing changed.'; return }
    $dir = Get-LatestMove
    if (-not $dir) { $dir = Join-Path $Root ('moves\cad-back-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
    Invoke-Step 'node' @($tool, 'back', $dir) $c.Dir
    Write-DeployLog 'cad-back' $c 'back on cados'
    Write-Host ''
    Write-Host 'Done. fly.website.toml must send bizomat.ai/cad to cados (UPSTREAM_CAD = "http://cados.internal:8080"): if the' -ForegroundColor Green
    Write-Host 'switch was merged on GitHub, revert it before the next deploy website (deploy website checks this).'
}

function Retire-Cados {
    # Step 1 of 2, once CAD Automation works from the cad group: cados's public addresses released. Irreversible.
    Write-Title 'Retire the Fly app cados, step 1 of 2: release its public addresses'
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    Assert-Node
    $c = Get-DeployCommit 'gocore-website'
    $tool = Get-CadTool $c.Dir
    # a preview: it refuses unless CAD Automation runs in the cad group and fly.website.toml agrees
    Invoke-Step 'node' @($tool, 'retire-ips') $c.Dir
    if ($DryRun) { Write-Host 'Dry run: nothing was released.' -ForegroundColor Yellow; return }
    Write-Host ''
    Write-Host 'This cannot be undone: the addresses go back to Fly, and every name above that points at them stops answering.' -ForegroundColor Yellow
    $typed = Read-Host 'Type release cados to release them (anything else stops)'
    if ("$typed".Trim() -ne 'release cados') { Write-Host 'Stopped. Nothing was released.'; return }
    Invoke-Step 'node' @($tool, 'retire-ips', '--confirm', 'cados') $c.Dir
    Write-DeployLog 'cados-ips' @{ Repo = 'gocore-website'; Short = $c.Short; Subject = 'cados: public addresses released' } 'released'
    Write-Host 'Later, at the end of the rollback window: .\bizomat.ps1 delete cados' -ForegroundColor Green
}

function Delete-Cados {
    # Step 2 of 2, at the end of the rollback window: the Fly app cados deleted, with its Machine and its volume.
    Write-Title 'Retire the Fly app cados, step 2 of 2: delete it, with its Machine and its volume'
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    Assert-Node
    $c = Get-DeployCommit 'gocore-website'
    $tool = Get-CadTool $c.Dir
    $last = Get-LatestMove
    if ($last) {
        try {
            $moved = Get-Prop (Get-Content -Raw -LiteralPath (Join-Path $last 'move.json') | ConvertFrom-Json) 'moved'
            $days = [int]((Get-Date).ToUniversalTime() - (ConvertTo-Utc $moved)).TotalDays
            Write-Host "CAD Automation moved $days day(s) ago ($last)."
        } catch { Write-Host "The move's record is in $last." }
    }
    Invoke-Step 'node' @($tool, 'delete-app') $c.Dir   # a preview: what goes with it
    if ($DryRun) { Write-Host 'Dry run: nothing was deleted.' -ForegroundColor Yellow; return }
    Write-Host ''
    Write-Host 'This cannot be undone: the old copy of the data goes with the app. The cad volume gets a snapshot first.' -ForegroundColor Yellow
    $typed = Read-Host 'Type delete cados to delete it (anything else stops)'
    if ("$typed".Trim() -ne 'delete cados') { Write-Host 'Stopped. Nothing was deleted.'; return }
    Invoke-Step 'node' @($tool, 'delete-app', '--confirm', 'cados') $c.Dir
    Write-DeployLog 'cados-delete' @{ Repo = 'gocore-website'; Short = $c.Short; Subject = 'cados: app deleted' } 'deleted'
    Write-Host 'Done. Delete the move folders too (moves\cad-*): they hold copies of the data with every key.' -ForegroundColor Green
}

# ----------------------------------------------------------------------------- kevos.com

function ConvertTo-Utc($Value) {
    # A JSON time in UTC, or $null when it is not one. PowerShell 7 reads it as a DateTime already; Windows PowerShell
    # 5.1 leaves the text, which Cloudflare may write with up to 9 decimals of a second (.NET reads at most 7).
    if ($Value -is [datetime]) {
        if ($Value.Kind -eq [DateTimeKind]::Unspecified) { return [datetime]::SpecifyKind($Value, [DateTimeKind]::Utc) }
        return $Value.ToUniversalTime()
    }
    $text = ("$Value".Trim()) -replace '(\.\d{7})\d+', '$1'
    $when = [datetimeoffset]::MinValue
    $styles = [Globalization.DateTimeStyles]::AssumeUniversal
    if ($text -and [datetimeoffset]::TryParse($text, [Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$when)) { return $when.UtcDateTime }
    return $null
}

function ConvertFrom-JsonList([string] $Text) {
    # The items of the first JSON list in a program's output. Windows PowerShell 5.1's ConvertFrom-Json hands a list
    # on as one object (PowerShell 7 hands on its items), so the list is unrolled here: the same answer in both.
    $m = [regex]::Match("$Text", '(?s)\[\s*(?:\{.*\})?\s*\]')
    if (-not $m.Success) { return $null }
    try { $json = ConvertFrom-Json -InputObject $m.Value } catch { return $null }
    return ,@($json | ForEach-Object { $_ })
}

function Restore-Kevos {
    # Stage 0 (owner's decision, 6 Nov 2026): kevos.com shows the KEVOS site again. The Cloudflare Worker behind it,
    # throbbing-block-6c61, goes back to the deployment that was live before the BIZOMAT website was published there
    # (gocore-website 33a77cb, 6 Nov 2026 01:03 UTC): the KEVOS site built from c79e297 (5 Nov). Then its routes become
    # kevos.com/* alone: bizomat.ai/* and www.bizomat.ai/* belong to the Fly app bizomat now. With this computer's
    # wrangler sign-in; nothing changes before you type yes, and the way back is shown first.
    Write-Title 'kevos.com: back to the KEVOS site (Cloudflare Worker throbbing-block-6c61)'
    Assert-Node
    $worker = 'throbbing-block-6c61'
    $published = [datetime]::SpecifyKind([datetime]'2026-11-06T01:03:28', [DateTimeKind]::Utc)
    $site = Join-Path $Root 'gocore-website'
    $wrangler = Join-Path (Join-Path (Join-Path (Join-Path $site 'node_modules') 'wrangler') 'bin') 'wrangler.js'
    if (-not (Test-Path -LiteralPath $wrangler)) { Stop-Here 'wrangler is not in the gocore-website folder: run .\bizomat.ps1 setup first.' }

    # wrangler runs in a folder of its own, with the Worker's name and route only: no other setting is read or sent
    $work = Join-Path ([IO.Path]::GetTempPath()) ('bizomat-kevos-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    [void](New-Item -ItemType Directory -Path $work)
    $config = Join-Path $work 'wrangler.toml'
    $lines = @(
        '# kevos.com alone (bizomat.ps1 restore kevos)',
        "name = `"$worker`"",
        'compatibility_date = "2025-09-01"',
        'workers_dev = false',
        'routes = [ { pattern = "kevos.com/*", zone_name = "kevos.com" } ]'
    )
    [IO.File]::WriteAllText($config, (($lines -join "`n") + "`n"))
    try {
        Write-Host 'Reading the Worker''s last 10 deployments (wrangler deployments list)...'
        $raw = Get-Output 'node' @($wrangler, 'deployments', 'list', '--name', $worker, '--json', '--config', $config) $work
        $deployments = $null
        if ($raw) { $deployments = ConvertFrom-JsonList $raw }
        if ($null -eq $deployments) {
            Stop-Here "wrangler could not list the Worker's deployments: not signed in (cd `"$site`"; npx wrangler login), or more than one Cloudflare account (`$env:CLOUDFLARE_ACCOUNT_ID = '<the account ID>', then run this again)."
        }
        # each deployment: when it was made and the versions it serves; any we cannot read stops everything
        $list = @(foreach ($d in $deployments) {
            $when = ConvertTo-Utc (Get-Prop $d 'created_on')
            if ($null -eq $when) { Stop-Here "wrangler's list of deployments was not understood (a deployment without a time: '$(Get-Prop $d 'created_on')'). Nothing was changed." }
            [pscustomobject]@{ When = $when; Versions = @(Get-Prop $d 'versions') }
        })
        $sorted = @($list | Sort-Object When)
        if ($sorted.Count -eq 0) { Stop-Here 'The Worker has no deployments. Nothing was changed.' }
        $live = $sorted[-1]
        $before = @($sorted | Where-Object { $_.When -lt $published })
        if ($before.Count -eq 0) {
            Stop-Here "The deployment from before 6 Nov 2026 01:03 UTC is not among the last 10. Nothing was changed. In the Cloudflare dashboard: Workers & Pages > $worker > Deployments: deploy the version of 5 Nov 2026 (the KEVOS site, c79e297)."
        }
        $target = $before[-1]
        $targetVersions = @($target.Versions)
        $liveVersions = @($live.Versions)
        if ($targetVersions.Count -ne 1) { Stop-Here "That deployment splits traffic between versions: deploy it from the dashboard (Workers & Pages > $worker > Deployments). Nothing was changed." }
        $want = "$(Get-Prop $targetVersions[0] 'version_id')"
        $now = ''
        if ($liveVersions.Count -eq 1) { $now = "$(Get-Prop $liveVersions[0] 'version_id')" }
        if ($want -notmatch '^[0-9a-f-]{36}$') { Stop-Here 'wrangler did not give a version ID for that deployment. Nothing was changed.' }
        Write-Host ''
        Write-Host ("  live now          deployment of {0:yyyy-MM-dd HH:mm} UTC, version {1}" -f $live.When, $(if ($now) { $now } else { '(several)' }))
        Write-Host ("  the KEVOS site    deployment of {0:yyyy-MM-dd HH:mm} UTC, version {1}" -f $target.When, $want)
        Write-Host "  kevos.com shows   $(Get-Title 'https://kevos.com/')"

        if ($now -eq $want) {
            Write-Host 'kevos.com already runs the KEVOS version; only its routes are set.' -ForegroundColor Green
            if ($DryRun) { Write-Host 'Dry run: stopping before the routes.' -ForegroundColor Yellow; return }
        } else {
            if ($DryRun) { Write-Host 'Dry run: every check is done; stopping before the change.' -ForegroundColor Yellow; return }
            if ($now) { Write-Host "The way back, if ever needed: node `"$wrangler`" rollback $now --name $worker" -ForegroundColor DarkGray }
            Write-Host ''
            $typed = Read-Host 'Put the KEVOS site back on kevos.com now? Type yes to continue (anything else stops)'
            if ("$typed".Trim() -ne 'yes') { Write-Host 'Stopped. Nothing was changed.'; return }
            Invoke-Step 'node' @($wrangler, 'rollback', $want, '--name', $worker, '--config', $config, '--yes', '--message', 'Stage 0: the KEVOS site again (built from c79e297); BIZOMAT is on Fly') $work
        }

        # The routes: kevos.com/* alone. wrangler replaces the Worker's whole list with this one.
        Invoke-Step 'node' @($wrangler, 'triggers', 'deploy', '--name', $worker, '--config', $config) $work

        Write-Title 'Live checks'
        $ok = Invoke-Checks @(
            @{ What = 'kevos.com shows the KEVOS site'; Test = { Wait-Until { $t = Get-Title 'https://kevos.com/'; ($t -match 'KEVOS') -and ($t -notmatch 'BIZOMAT') } 120 } },
            @{ What = 'bizomat.ai shows the BIZOMAT website (Fly)'; Test = { (Get-Title 'https://bizomat.ai/') -match 'BIZOMAT' } }
        )
        $result = if ($ok) { 'ok' } else { 'restored; live checks failed' }
        Write-DeployLog 'kevos' @{ Repo = 'gocore-website'; Short = 'c79e297'; Subject = "kevos.com: the KEVOS site again (version $want)" } $result
        if (-not $ok) { Stop-Here "A live check failed. kevos.com shows: $(Get-Title 'https://kevos.com/'). Look at Workers & Pages > $worker > Deployments in the Cloudflare dashboard." }
        Write-Host 'Done: kevos.com is the KEVOS site again.' -ForegroundColor Green
        Write-Title 'One click left, in the Cloudflare dashboard'
        Write-Host "  Workers & Pages > $worker > Settings > Build > Disconnect."
        Write-Host '  Then nothing on GitHub can publish to kevos.com again. Until then, gocore-website stops such a build before it deploys.'
    } finally {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ----------------------------------------------------------------------------- main

switch ($Command) {
    'setup' { Invoke-Setup }
    'status' { Show-Status }
    'deploy' {
        switch ($App) {
            'website' { Deploy-Website }
            'cad' { Deploy-Cad }
            'tasks' { Deploy-Tasks }
            default { Stop-Here 'Say which: .\bizomat.ps1 deploy website | cad | tasks' }
        }
    }
    'secrets' {
        if ($App -eq 'website') { Set-WebsiteSecrets } else { Stop-Here 'Say which: .\bizomat.ps1 secrets website' }
    }
    'sync' {
        if ($App -eq 'cad') { Sync-Cad } else { Stop-Here 'Say which: .\bizomat.ps1 sync cad' }
    }
    'move' {
        switch ($App) {
            'tasks' { Move-Tasks }
            'cad' { Move-Cad }
            default { Stop-Here 'Say which: .\bizomat.ps1 move tasks | cad' }
        }
    }
    'back' {
        if ($App -eq 'cad') { Back-Cad } else { Stop-Here 'Say which: .\bizomat.ps1 back cad' }
    }
    'retire' {
        if ($App -eq 'cados') { Retire-Cados } else { Stop-Here 'Say which: .\bizomat.ps1 retire cados' }
    }
    'delete' {
        if ($App -eq 'cados') { Delete-Cados } else { Stop-Here 'Say which: .\bizomat.ps1 delete cados' }
    }
    'restore' {
        if ($App -eq 'kevos') { Restore-Kevos } else { Stop-Here 'Say which: .\bizomat.ps1 restore kevos' }
    }
    default { Get-Help -Detailed $PSCommandPath }
}

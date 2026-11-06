<#
.SYNOPSIS
  BIZOMAT from your own computer: one folder holding the three repositories, and every deploy made from it.

.DESCRIPTION
  Keep this file in the folder that holds everything (for example C:\BIZOMAT), then run:

    .\bizomat.ps1 setup            clone CADOS, gocore-website and PMO next to this file, or bring them up to date
    .\bizomat.ps1 status           each folder's state, GitHub's checks and what is live
    .\bizomat.ps1 deploy website   the BIZOMAT website: Cloudflare Worker throbbing-block-6c61 (kevos.com, bizomat.ai)
    .\bizomat.ps1 deploy cad       CAD Automation: Fly app cados (bizomat.ai/cad)
    .\bizomat.ps1 deploy tasks     Project Management: Cloudflare Worker workos-platform-preview (work.kevos.com)

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
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)] [ValidateSet('setup', 'status', 'deploy', 'help')] [string] $Command = 'help',
    [Parameter(Position = 1)] [ValidateSet('website', 'cad', 'tasks')] [string] $App = '',
    [switch] $DryRun,
    [switch] $SkipChecks,
    [switch] $ApplyMigrations
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
    $cad = Get-Json 'https://cados.fly.dev/healthz'
    $cadVersion = if ($cad) { $cad.version } else { 'no answer' }
    $tasks = Get-Json 'https://work.kevos.com/api/health'
    $tasksState = if ($tasks) { "$($tasks.status), database $($tasks.db)" } else { 'no answer' }
    $site = if ((Get-Body 'https://kevos.com/') -match '<title>BIZOMAT') { 'BIZOMAT website' } else { 'not the BIZOMAT website' }
    $biz = if ((Get-Body 'https://bizomat.ai/') -match '<title>BIZOMAT') { 'BIZOMAT website' } else { 'not yet the website (its DNS records are not proxied)' }
    Write-Host "  kevos.com          $site"
    Write-Host "  bizomat.ai         $biz"
    Write-Host "  CAD Automation     version $cadVersion (cados.fly.dev/healthz)"
    Write-Host "  Project Management $tasksState (work.kevos.com/api/health)"
}

# ----------------------------------------------------------------------------- deploys

function Deploy-Website {
    Write-Title 'BIZOMAT website: Cloudflare Worker throbbing-block-6c61 (kevos.com, bizomat.ai)'
    Assert-Node
    $c = Get-DeployCommit 'gocore-website'
    Show-Commit $c
    if (-not $SkipChecks) {
        Invoke-Step 'npm' @('ci', '--no-audit', '--no-fund') $c.Dir
        Invoke-Step 'npm' @('run', 'verify') $c.Dir   # type check, the test suite, the build and its page checks
    }
    if (-not (Confirm-Deploy 'the BIZOMAT website (kevos.com, bizomat.ai)')) { return }
    Invoke-Step 'npx' @('wrangler', 'deploy', '--message', "$($c.Short) from $env:COMPUTERNAME") $c.Dir
    Write-Title 'Live checks'
    [void](Wait-Until { (Get-Code 'https://kevos.com/insights') -eq 301 } 120)
    $ok = Invoke-Checks @(
        @{ What = 'kevos.com shows the BIZOMAT website'; Test = { (Get-Body 'https://kevos.com/') -match '<title>BIZOMAT' } },
        @{ What = 'paths that are not files reach the Worker (/insights redirects)'; Test = { (Get-Code 'https://kevos.com/insights') -eq 301 } },
        @{ What = 'the assistant answers (/api/chat, no AI call made)'; Test = { (Get-Code 'https://kevos.com/api/chat' 'POST' '{}') -eq 422 } },
        @{ What = 'the old CAD page /cad/ redirects to /cad-automation/'; Test = { (Get-Code 'https://kevos.com/cad/') -eq 301 } },
        @{ What = 'bizomat.ai shows the website'; Info = $true; Test = { (Get-Body 'https://bizomat.ai/') -match '<title>BIZOMAT' } }
    )
    $result = if ($ok) { 'ok' } else { 'deployed; live checks failed' }
    Write-DeployLog 'website' $c $result
    if (-not $ok) { Stop-Here 'The deploy finished but a live check failed. Look at the site; to go back, Cloudflare > Workers & Pages > throbbing-block-6c61 > Deployments > roll back.' }
    Write-Host 'Done.' -ForegroundColor Green
}

function Deploy-Cad {
    Write-Title 'CAD Automation: Fly app cados (bizomat.ai/cad)'
    Assert-Tool 'fly' 'Install flyctl: iwr https://fly.io/install.ps1 -useb | iex  then: fly auth login'
    $c = Get-DeployCommit 'CADOS'
    Show-Commit $c
    $checks = Get-Checks 'CADOS' $c.Commit
    Write-Host "GitHub's checks on $($c.Short): $checks"
    if ($checks -ne 'passed' -and -not $SkipChecks) {
        Stop-Here "CAD Automation's tests run on GitHub (they need the CAD libraries and SOLIDWORKS stand-ins). Deploy once they pass."
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
    default { Get-Help -Detailed $PSCommandPath }
}

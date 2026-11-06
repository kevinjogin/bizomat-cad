# BIZOMAT on your laptop

One folder holds the three repositories, and every deploy is made from it with `bizomat.ps1`. GitHub stays the home
of the code (history, backup, pull requests); deploys come from your laptop, not from GitHub.

| App | Repository | Where it runs | Deploy command |
| --- | --- | --- | --- |
| BIZOMAT website (bizomat.ai) | `gocore-website` | Fly.io app `bizomat` (Sydney): the website, the router in front of it, Project Management (`bizomat.ai/tasks`) and CAD Automation's group | `.\bizomat.ps1 deploy website` |
| CAD Automation (bizomat.ai/cad) | `CADOS`, copied into `gocore-website/apps/cad` | Until `move cad`: the Fly.io app `cados` (Amsterdam). After it: the `cad` group of the Fly app `bizomat` (Sydney), with its data (below: CAD Automation into bizomat) | `.\bizomat.ps1 deploy cad` |
| Project Management (bizomat.ai/tasks) | `PMO`, in `gocore-website/apps/work` | The Fly app `bizomat` (moved from Cloudflare with `move tasks`) | `.\bizomat.ps1 deploy website` |

The website and CAD Automation run on Fly.io. Project Management stays on Cloudflare until it moves to Fly with its
data; it deploys from the laptop the same way, with Cloudflare's `wrangler` instead of `fly`. The website answers on
bizomat.fly.dev until bizomat.ai's DNS points at the `bizomat` app. kevos.com goes back to the old KEVOS site on
Cloudflare (Worker `throbbing-block-6c61`), which nothing here deploys.

## Once

1. Install:
   - Git for Windows: https://git-scm.com/download/win
   - Node.js 22 LTS (22.19 or newer): https://nodejs.org
   - flyctl, in PowerShell: `iwr https://fly.io/install.ps1 -useb | iex`

   Then open a new PowerShell window.
2. In a **normal** PowerShell window (not "Run as administrator", which opens in `C:\WINDOWS\System32` and makes
   the files belong to the administrator), make the folder and download the script into it. The script uses its own
   folder as the BIZOMAT folder:
   ```powershell
   mkdir C:\BIZOMAT
   cd C:\BIZOMAT
   curl.exe -fsSL -o bizomat.ps1 https://raw.githubusercontent.com/jogkev-creator/CADOS/main/tools/laptop/bizomat.ps1
   curl.exe -fsSL -o README.md https://raw.githubusercontent.com/jogkev-creator/CADOS/main/tools/laptop/README.md
   ```
3. Clone everything. `gocore-website` is private, so Git opens a browser once for your GitHub sign-in:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\bizomat.ps1 setup
   ```
4. Sign in to the two hosts (each opens a browser once):
   ```powershell
   fly auth login
   cd C:\BIZOMAT\PMO; npx wrangler login; cd C:\BIZOMAT
   ```
5. Check: `powershell -ExecutionPolicy Bypass -File .\bizomat.ps1 status`

If your Cloudflare sign-in can see more than one account, wrangler asks which one when it deploys. Set it once per
window with `$env:CLOUDFLARE_ACCOUNT_ID = '<the account ID>'`; the ID is on the dashboard's Workers & Pages overview.

To type `.\bizomat.ps1 ...` directly instead of the long form, allow your own scripts once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Every deploy

1. Changes reach GitHub first: a pull request, merged into the repository's main branch.
2. Then, on the laptop:
   ```powershell
   cd C:\BIZOMAT
   .\bizomat.ps1 deploy website      # or: cad, tasks
   ```

What the script does, in order:
1. **Refuses** anything that is not exactly GitHub's main branch: another branch, local edits, or commits GitHub does
   not have. If the folder is only behind, it brings it up to date first. An old checkout replaced the website once
   (8 Oct 2026); this rule is what prevents it.
2. **Checks** the code:
   - website: type check, the test suite, the full build and its page checks, and the router's tests (a few
     minutes);
   - tasks: lint, type check, tests, build;
   - cad: requires GitHub's checks on that commit to have passed, since its tests need the CAD libraries.
3. **Shows** the commit that will go live and asks you to type `yes`.
4. **Deploys**, then checks the live addresses. For example, the website's check confirms that its APIs answer and
   that `/cad` reaches CAD Automation over Fly's private network. The first website deploy creates the Fly app
   `bizomat` (after asking).
5. **Records** the deploy in `deploy-log.csv` in the folder: when, what, which commit and who.

Useful switches:
- `-DryRun`: everything except the deploy.
- `-ApplyMigrations`: tasks only. Applies database migrations waiting on the live database, after printing a restore
  point. Normally there are none, and without this switch the script stops if there are.

## The website's AI (once)

The website's assistant and AI search use Cloudflare Workers AI. After the first website deploy:
```powershell
.\bizomat.ps1 secrets website
```
It asks for your Cloudflare account ID and a token made with Cloudflare's **Workers AI** template (My Profile > API
Tokens > Create Token), checks them with Cloudflare and saves them on Fly. What you type for the token stays hidden:
it is not shown, not kept in PowerShell's history and not written to a file. Run it again to replace the token.

## Project Management to Fly (once)

Project Management moves from Cloudflare (work.kevos.com) into the Fly app `bizomat`, at bizomat.ai/tasks, with its
data. In order:

1. `.\bizomat.ps1 deploy website`: the first deploy with Project Management creates its Machine and its data volume
   (3 GB, a snapshot every day). bizomat.ai/tasks still sends people to work.kevos.com.
2. Tell the people who use work.kevos.com about a short pause, and change nothing there until step 5.
3. `.\bizomat.ps1 move tasks`: it exports the data from Cloudflare (only reading it), checks every table and file and
   shows the counts. Type `yes` and it uploads the copy, checks it on Fly and puts it in place (what was there is kept
   in a backup on the volume). The copy also stays in `C:\BIZOMAT\moves\tasks-<time>\`: it holds real data, so
   delete it once step 5 is checked. Add `-DryRun` to export and check only.
4. Check it before anyone else sees it: open https://bizomat.fly.dev/__preview/work, sign in with your own email and
   password, and compare a board, a document and a file with work.kevos.com. https://bizomat.fly.dev/__preview/clear
   takes that browser back to the website.
5. The switch (a change on GitHub, then `.\bizomat.ps1 deploy website`): bizomat.ai/tasks is Project Management on
   Fly. Everyone signs in there once more.
6. Then work.kevos.com moves to Fly too, so its old links keep working (gocore-website `docs/BIZOMAT-DEPLOYMENT.md`,
   section 6c).

If wrangler says it sees more than one Cloudflare account, set `$env:CLOUDFLARE_ACCOUNT_ID = '<the account ID>'` in
that window first.

## CAD Automation into bizomat (once)

CAD Automation moves from its own Fly app `cados` (one Machine and its volume in Amsterdam) into the `cad` group of the
Fly app `bizomat` in Sydney, with its data: the same accounts, AI app connections, paired computers and signing keys,
so connectors (`https://bizomat.ai/cad/mcp`) and paired computers keep working. The whole plan, what moves and why:
gocore-website `infrastructure/migrate/cad/README.md`. In order:

1. `.\bizomat.ps1 deploy website` (once gocore-website has the cad group): it checks that `apps/cad` is exactly the
   CADOS commit it names, makes the volume `cad_data` (3 GB in Sydney, a snapshot every day kept 30 days) and deploys.
   The cad Machine shows a holding page; bizomat.ai/cad is still served by cados.
2. `.\bizomat.ps1 move cad -DryRun`: every check, and a copy of the data taken while cados keeps running, brought here
   and checked file by file. Nothing changes. The copy is in `C:\BIZOMAT\moves\cad-<time>\`.
3. Tell the people who use CAD Automation about a pause of a few minutes, then `.\bizomat.ps1 move cad`: the same checks,
   type yes, and it moves it: bizomat.ai/cad says "being moved", cados is frozen, the data copied, checked on both
   sides and imported, the CAD server started with it, live checks (the same signing key, the accounts, OAuth), and
   cados stopped so it cannot serve the old copy. If a step fails, it goes back to cados by itself. `-Force` replaces
   data an earlier attempt left on the cad volume (kept in `/data/backups`).
4. Check it yourself: sign in at https://bizomat.ai/cad/login; Admin lists the same people, Settings shows the same
   private connector address, SOLIDWORKS lists the same computers; ask your AI app to run `sw_status`.
5. Make the route permanent: merge the gocore-website change that sets `UPSTREAM_CAD =
   "http://cad.process.bizomat.internal:8001"` in `fly.website.toml`. Until it is merged, `deploy website` stops, so
   no deploy can send bizomat.ai/cad back to the old copy.
6. Only when you are sure, and at your go-ahead: `.\bizomat.ps1 retire cados` (releases cados's public addresses:
   `cados.fly.dev` and every name pointing at them stop answering; type `release cados`), and at the end of the
   rollback window `.\bizomat.ps1 delete cados` (the app, its Machine and its volume; type `delete cados`). Neither can
   be undone. Then delete the `moves\cad-*` folders: they hold copies of the data with every key.

The way back after a move: `.\bizomat.ps1 back cad` (cados again, with its data as at the move; what changed in the cad
group since then stays there). Old addresses: `cados.kevos.com` and `cados.fly.dev` reach cados directly and stop
answering when it stops; computers with the 0.13 Companion use bizomat.ai/cad by themselves. To keep
`cados.kevos.com`, move it to `bizomat` (a certificate, then its DNS record: a production DNS change, so yours to
approve).

After the move, `.\bizomat.ps1 deploy cad` deploys CADOS main to the cad group alone. It needs `apps/cad` in
gocore-website to be CADOS main: `.\bizomat.ps1 sync cad` makes the branch that brings it across (it pushes it to
GitHub and prints the pull request link, title ending in `[skip ci]`); merge it, then deploy. `deploy website` leaves
CAD Automation running unless its code or the platform scripts changed. `sync cad` makes a commit: Git needs your name
and email once (`git config --global user.name ...` and `user.email ...`).

## kevos.com back to the KEVOS site (once)

kevos.com showed the BIZOMAT website from 6 Nov 2026, when it went live there before moving to Fly. To put the KEVOS
site back (Stage 0):

```powershell
.\bizomat.ps1 restore kevos
```

It uses wrangler's sign-in on this computer (`npx wrangler login` in `gocore-website`, done in setup). It shows the
deployment that is live now and the one it will put back, the last one before 6 Nov 2026 01:03 UTC (the KEVOS site,
built from gocore-website `c79e297`), with the command that undoes it. Type `yes` and it puts that version back on the
Worker `throbbing-block-6c61`, then sets its routes to `kevos.com/*` alone (bizomat.ai is served by Fly). It finishes
by checking that kevos.com shows KEVOS and bizomat.ai still shows BIZOMAT. Add `-DryRun` to see what it would do. Run
it again at any time: when kevos.com already runs that version, it only sets the routes.

Then one click in the Cloudflare dashboard, which wrangler cannot do: Workers & Pages > `throbbing-block-6c61` >
Settings > Build > Disconnect. Until then, gocore-website stops any such build before it deploys.

## Going back

| App | How |
| --- | --- |
| website | `fly releases -a bizomat --image`, then in `gocore-website`: `fly deploy --config fly.website.toml -a bizomat --image <the previous image> --ha=false` |
| cad (after move cad) | `fly releases -a bizomat --image`, then in `gocore-website`: `fly deploy --config fly.website.toml -a bizomat --image <the previous image> --process-groups cad --ha=false` |
| cad (before move cad) | `fly releases -a cados --image`, then `fly deploy -a cados --image <the previous image>` |
| the CAD move | `.\bizomat.ps1 back cad` |
| tasks | `npx wrangler rollback --env preview` in `PMO` |
| kevos.com | the command `restore kevos` showed before it started (`node ... rollback <version> --name throbbing-block-6c61`) |

## So that only the laptop deploys

- **Website:** Cloudflare's Git connection on the old Worker (`throbbing-block-6c61`, kevos.com) should be off:
  Cloudflare dashboard > Workers & Pages > `throbbing-block-6c61` > Settings > Build > Disconnect. Until it is,
  gocore-website refuses to build there (its `wrangler.toml` runs `scripts/kevos-guard.mjs` first), so kevos.com
  keeps the KEVOS site.
- **CAD and Project Management:** GitHub already deploys neither. CADOS has no Fly token on GitHub, and PMO's deploy
  workflows are switched off by its `CLOUDFLARE_DEPLOY_ENABLED` setting.

## Keep in mind

- **The laptop now holds the keys to production.** Fly's and Cloudflare's sign-ins live in your user profile; the
  website's Workers AI token lives only on Fly. Keep
  the laptop encrypted (BitLocker) and locked when you step away. To sign out on a lost laptop: `fly auth logout`,
  `npx wrangler logout`, and remove the sessions in the Fly and Cloudflare dashboards.
- **Never keep code only on the laptop.** Everything goes through GitHub first; the folder is a working copy.
  Re-running `setup` on a new laptop rebuilds it in minutes.

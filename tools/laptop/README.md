# BIZOMAT on your laptop

One folder holds the three repositories, and every deploy is made from it with `bizomat.ps1`. GitHub stays the home
of the code (history, backup, pull requests); deploys come from your laptop, not from GitHub.

| App | Repository | Where it runs | Deploy command |
| --- | --- | --- | --- |
| BIZOMAT website (kevos.com, bizomat.ai) | `gocore-website` | Cloudflare Worker `throbbing-block-6c61` | `.\bizomat.ps1 deploy website` |
| CAD Automation (bizomat.ai/cad) | `CADOS` | Fly.io app `cados` | `.\bizomat.ps1 deploy cad` |
| Project Management (work.kevos.com, bizomat.ai/tasks) | `PMO` | Cloudflare Worker `workos-platform-preview` | `.\bizomat.ps1 deploy tasks` |

Only CAD Automation runs on Fly.io. The website and Project Management run on Cloudflare: they deploy from the laptop
the same way, with Cloudflare's `wrangler` instead of `fly`.

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
   curl.exe -fsSL -o bizomat.ps1 https://raw.githubusercontent.com/jogkev-creator/CADOS/claude/dazzling-mccarthy-31qg86/tools/laptop/bizomat.ps1
   curl.exe -fsSL -o README.md https://raw.githubusercontent.com/jogkev-creator/CADOS/claude/dazzling-mccarthy-31qg86/tools/laptop/README.md
   ```
3. Clone everything. `gocore-website` is private, so Git opens a browser once for your GitHub sign-in:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\bizomat.ps1 setup
   ```
4. Sign in to the two hosts (each opens a browser once):
   ```powershell
   fly auth login
   cd C:\BIZOMAT\gocore-website; npx wrangler login; cd C:\BIZOMAT
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
   - website: type check, the test suite, the full build and its page checks (a few minutes);
   - tasks: lint, type check, tests, build;
   - cad: requires GitHub's checks on that commit to have passed, since its tests need the CAD libraries.
3. **Shows** the commit that will go live and asks you to type `WEBSITE`, `CAD` or `TASKS`.
4. **Deploys**, then checks the live addresses. For example, the website's check confirms the assistant and the
   other APIs still reach the Worker.
5. **Records** the deploy in `deploy-log.csv` in the folder: when, what, which commit and who.

Useful switches:
- `-DryRun`: everything except the deploy.
- `-ApplyMigrations`: tasks only. Applies database migrations waiting on the live database, after printing a restore
  point. Normally there are none, and without this switch the script stops if there are.

## Going back

| App | How |
| --- | --- |
| website | Cloudflare dashboard > Workers & Pages > `throbbing-block-6c61` > Deployments > roll back, or `npx wrangler rollback` in `gocore-website` |
| cad | `fly releases -a cados --image`, then `fly deploy -a cados --image <the previous image>` |
| tasks | `npx wrangler rollback --env preview` in `PMO` |

## So that only the laptop deploys

- **Website:** Cloudflare still builds and deploys every push to `main` of gocore-website on its own. That's harmless,
  because both deploy the same commit, but it's a second way in, and it is the one that stalled on 6 Nov. To leave
  only the laptop: Cloudflare dashboard > Workers & Pages > `throbbing-block-6c61` > Settings > Builds > Disconnect.
- **CAD and Project Management:** GitHub already deploys neither. CADOS has no Fly token on GitHub, and PMO's deploy
  workflows are switched off by its `CLOUDFLARE_DEPLOY_ENABLED` setting.

## Keep in mind

- **The laptop now holds the keys to production.** Fly's and Cloudflare's sign-ins live in your user profile. Keep
  the laptop encrypted (BitLocker) and locked when you step away. To sign out on a lost laptop: `fly auth logout`,
  `npx wrangler logout`, and remove the sessions in the Fly and Cloudflare dashboards.
- **Never keep code only on the laptop.** Everything goes through GitHub first; the folder is a working copy.
  Re-running `setup` on a new laptop rebuilds it in minutes.

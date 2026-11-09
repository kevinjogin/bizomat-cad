# CLAUDE.md

Guidance for AI coding agents (and people) working on CAD MCP and BIZOMAT CAD for Windows.

**Since 8 Nov 2026 this folder (`apps/cad` in `jogkev-creator/bizomat`) is where CAD Automation is changed.** It was
imported from `jogkev-creator/CADOS` at e669cc6 (`../apps/cad-source.json`); CADOS keeps the history and the installer
backups (`backups/installer`, not copied here). Production is the single Fly app `cados` (one Machine, 1 GB) described
in `../docs/BIZOMAT-SINGLE-APP.md`: this server runs there as the `cad` role of `bizomat-entrypoint all`, with its data
in `/data/cad`, CAD geometry in its own process (`OPENSKETCH_CAD_WORKERS=0`), behind the platform proxy. It is
deployed only by `../.github/workflows/deploy.yml`; the add-in and MSI are built by
`../.github/workflows/cad-windows.yml`. The `.github/workflows` of CADOS were moved there or retired; where this file
mentions `deploy.yml`, `solidworks.yml`, `tests.yml`, `domain.yml`, `fly-status.yml`, the cados `fly.toml` or Fly's own
GitHub deploys, read the root workflows and `../fly.toml` instead.

**BIZOMAT CAD (owner, 8 Nov 2026):** the Windows add-in, its toolbar, task pane, status window, installer, Start menu and
messages are called **BIZOMAT CAD** (0.14.0; "BIZOMAT CAD Automation" up to 0.13). Its folder is
`Documents\BIZOMAT CAD` (Documents from the Windows known-folder API, local or OneDrive) with Settings, Projects,
Templates, Logs, Cache and Backups (`solidworks/src/Core/UserFolders.cs`): saves and exports default to Projects, the
log is `Logs\log.txt`, the manual installer's launcher macro is `BIZOMAT CAD.swb` in the root, working copies go to
`%TEMP%\BIZOMAT CAD` (never synced). Nothing creates an `OpenSketch` folder any more. On its first start the add-in
(and the manual installer's Install for me) copies the old `Documents\OpenSketch` files into Projects once: copies
only, never overwrites (a different file of the same name is kept beside it as "name (from earlier folder).ext"),
never deletes; locked or syncing files are retried at the next start; the record is `Backups\Earlier folder
migration.json` and the old folder gets a note.

**No "OpenSketch" where people or AI apps can see it (owner, 9 Nov 2026), also in the background:** the manual
installer is `BIZOMAT-CAD.exe` (was OpenSketchSW.exe), the add-in package and its zip `BIZOMAT-CAD-SOLIDWORKS` (was
OpenSketch-SOLIDWORKS), the shipped launcher macro `BIZOMAT CAD.swb`, the User-Agent `BIZOMAT-CAD-SOLIDWORKS/<version>`,
log lines `BIZOMAT CAD request|worker|supervisor:`, module docstrings and the MCP guide say BIZOMAT CAD. Kept on purpose,
because installs, macros and saved keys depend on them (renaming them needs a migration tested on Windows): the add-in
file `OpenSketch.Sw.dll` and its namespace, the COM ProgIDs and CLSIDs (`OpenSketch.Sw.SwAddin`, `OpenSketch.Sw.Launcher`:
earlier launcher macros call it), the registry key `HKCU\Software\OpenSketch\SolidWorks` with the encrypted add-in key
and its DPAPI entropy, the upload header `X-OpenSketch-Gzip` that earlier add-ins send, the old folder and file names the
migration recognises, the Python package `opensketch` and the `OPENSKETCH_*` settings (Fly secrets use these names),
the MSI file names `BIZOMAT-CAD-Automation-*.msi` that the update record and download links use, and the MCP tool names
and endpoints. Tests: `solidworks/tests/UserFoldersTests.cs`, `tests/test_installer.py`
(`test_no_code_makes_an_opensketch_folder`, `test_the_msi_never_touches_documents_so_uninstall_keeps_user_files`),
`.github/scripts/test-install.ps1` (repair keeps one registration; uninstall keeps Documents files).

## What this repo is

CADOS by KEVOS (product name; the code keeps OpenSketch as its internal name: the `opensketch` package,
`OPENSKETCH_*` settings, cookies, the add-in's COM ids and file names, the MCP tool names) connects AI apps (Claude,
ChatGPT and other MCP clients) to SOLIDWORKS on the user's own PC. The AI
calls the `sw_` MCP tools; the server checks each sketch and feature with OpenSketch's build123d/OpenCascade
kernel, queues the work, and the OpenSketch add-in in SOLIDWORKS (`solidworks/`, C#) fetches it over outgoing HTTPS
and makes native SOLIDWORKS features. A home page sets it up. License: AGPL-3.0-only.

CADOS for SOLIDWORKS (0.12.3; called KEVOS Bridge up to 0.11) builds on it: the server is the CADOS gateway; each
Windows computer runs the native CADOS add-in (COM `ISwAddin`, Tools > Add-Ins > CADOS, CADOS tab, menu and task pane)
and the KEVOS Companion (tray app, starts with Windows, registered by pairing) which holds a signed outbound link to the
gateway and hands commands to the add-in over a local named pipe; one MSI ("CADOS for SOLIDWORKS") installs both.
`docs/CADOS-ADDIN.md` has the architecture, the gap report (there was never a macro product: the add-in was always a
COM add-in) and the release process. Docs: `docs/BRIDGE-PROTOCOL.md` (the contract),
`docs/KEVOS-*.md` (install, Cloudflare, security, versions, troubleshooting, build, signing, test report, release
notes). The MSI builds unsigned on Windows in CI (`installer` job); release signing waits for a signing service.
Development signing (`installer/sign-development.ps1`, `docs/BIZOMAT-DEV-SIGNING.md`) runs on the Windows development
computer with a self-signed `CN=BIZOMAT Development` certificate from its certificate store (not trusted elsewhere);
`installer-test.yml` runs it with a throwaway certificate. Installer backups: `backups/installer/` (original, as
released; development-signed), never overwritten.

## Rules

- After completing any phase or significant change, update this file to reflect the current state before committing.
- Test before committing: `pytest -q` (needs node for the sketch solver; the slow KEVOS end-to-end test needs the .NET
  8 SDK) and `npm test` (the solver alone); the add-in and Companion with `bash solidworks/build.sh test` (.NET 8 SDK).
  For page changes, check the page in Chromium with
  Playwright at desktop and phone width.
- No emojis anywhere. Plain language, short sentences, little text on pages.
- BIZOMAT corporate footer (owner, 8 Nov 2026; the website's `src/config/platform.ts` is the source): `brand.SLOGAN`
  ("Connecting Intelligence. Empowering Progress."), `brand.CORPORATE` (short description) and
  `brand.copyright_line()` ("(c) <year> BIZOMAT. All rights reserved.") in the site footer, the app footer and the
  sign-in panel; the footer's BIZOMAT column links Home, About (/engine-room/), Products, Project Management and
  Contact on bizomat.ai; legal links read Privacy Policy and Terms of Use. Product name, headline, logo and colours unchanged.
- Brand: never "OpenSketch" in anything people read (pages, MCP server name, messages, Windows names, folders); the
  Windows product is BIZOMAT CAD and its folder Documents\BIZOMAT CAD (above). Only the compatibility names listed
  above keep OpenSketch. Logos are SVG paths in
  `brand.py`: the CADOS wordmark (built from the KEVOS letterforms) with "by KEVOS"; the KEVOS logo links to
  https://kevos.com/. One design system for every page: tokens and components in `opensketch/static/ui/cados.css`,
  set to kevos.com's own tokens (its `src/styles/global.css`: paper #fbfaf7, ink #1c1b19, muted #69665f, logo orange
  #ff6a13 for marks, accent #c2410c for buttons and links, hover #9a3412, 8 px buttons, 14 px cards, one family
  Inter Tight), shared head/header/footer in `brand.py`. The KEVOS wordmark path and the favicon are kevos.com's
  official files (`static/ui/kevos-wordmark.svg`, `static/favicon.svg`; `favicon.ico` and `ui/icon-*.png` are
  rendered from it). Light theme. System monospace for technical labels; fonts served from `opensketch/static/fonts` (no third-party
  requests: the privacy page says so). Copy claims only what the code does (site.py says where each comes from).
- The feature format (`docs/DOCUMENT.md`, the registry in `opensketch/features/`) is the contract between the AI,
  the kernel and the add-in. Change it there first, then the kernel, then the add-in. The bridge protocol
  (`docs/BRIDGE-PROTOCOL.md`) is the contract between gateway, Companion and add-in: change it there first, then
  `devicebridge.py`, then `solidworks/src/Core/Bridge2`, and keep `tests/bridge_fakes.py` and BridgeProbe in step.
- SOLIDWORKS API calls only on SOLIDWORKS' UI thread (Host marshals); never from the Companion (it may only start
  SOLIDWORKS or ask it once to LoadAddIn) and never from a service. Code that runs inside SOLIDWORKS (the add-in, the
  pipe link) must never let an exception escape a thread: it would close SOLIDWORKS.
- Heavy work never runs on the web server's event loop: OpenCascade goes through the person's "agent" CAD worker
  (`cadworker.lane_for(person, "agent")`), node and big file writes through threads.
- No personal, client or confidential details in code, comments, tests or docs (the repository is private since 7 Nov
  2026, but it may be shared). Nothing public may link to GitHub: every repository is private, so its pages, releases
  and raw files answer 404 to everyone else. Downloads are published on bizomat.ai (`/downloads/cad/`, R2).
- CI (since 8 Nov 2026, in the bizomat repository's root `.github/workflows/`; workflows under `apps/cad/.github/` do
  not run): `bizomat-ci.yml` (the `cad` job: pytest in two parts, main and `-m slow`; `cad-npm`: npm test) on pull
  requests that change code and by hand; `cad-windows.yml` (the add-in, the Companion, the MSI on Windows) on pull
  requests that change `solidworks/` or `installer/`, on a tag `bridge-v*` and by hand; `deploy.yml` deploys to the
  Fly app `cados` only when run by hand (confirm DEPLOY, branch main). GitHub Free: the minutes are scarce, so
  nothing runs on every push. The CADOS workflows described below (`tests.yml`, `solidworks.yml`, `installer-test.yml`,
  `domain.yml`, `fly-status.yml`) are history. Python pins live in requirements.txt (image) and
  requirements-dev.txt (CI), with hashes.

## Current state (v0.8 server, BIZOMAT CAD add-in 0.15.0 on this branch; 0.14.0 released)

- KEVOS registered computers (`devicebridge.py`, router included in `server.py`): pairing (`/v2/devices/pair/*`, the
  signed-in page `/devices/pair`), device proofs (`Authorization: KEVOS-Device <JWS>`, ES256 by the computer's
  key: method, path, time, one-time id, body hash), the gateway's command key (`bridge-signing-key.pem` in the data
  folder; commands and cancels are JWS the Companion verifies), SQLite `bridge.sqlite` (devices, pairings, every
  command with its history and result), live sessions in memory, `/v2/device/*` (hello, long-poll next, ack,
  progress, status, chunked file, result, blob, unpair), `/v2/bridge/update.json` (signed release manifest from
  `bridge-release.json`), `/api/devices` (list, default, remove). `swbridge.call(..., device=)` routes to a computer
  when one is online (`devicebridge.pick`: by name, the only one, the only one with SOLIDWORKS, the default, else
  `DEVICE_AMBIGUOUS`), else to the v1 add-in link; `swbridge.status` adds the computers. On an open server (no
  password, no accounts) pairing is taken only from the server's own machine. Tests: `tests/test_devicebridge.py`
  with the stand-in Companion `tests/bridge_fakes.py` (every SOLIDWORKS tool and the self test run through a
  computer), `tests/test_bridge_e2e.py` (slow: the C# Companion and add-in link, `solidworks/tests/BridgeProbe`).
- MCP (`mcp_server.py`): one MCPServer "CADOS" with INSTRUCTIONS for SOLIDWORKS work and 31 tools: every `sw_`
  tool (`sw_tools.py`, `sw_selftest.py`, registered on `mcp` at import) plus `request_upload`. Every tool that reaches
  SOLIDWORKS takes an optional `device` (the `_routed` decorator sets `_DEVICE`/`_TOOL` for `_run`, `_geometry`, whose
  cache is per person and computer, and the status checks); `sw_list_devices`, `sw_command_status`,
  `sw_cancel_command` are new. The gates record the AI app's grant ({id, name}, no token) and a correlation id for
  commands. `Endpoint` serves it
  at each path in `PATHS` = ("/mcp", "/solidworks/mcp"): the path itself takes a Bearer token (`_BearerGate`, 401
  with the protected-resource pointer for that path), `path/<key>` the private address (`_TokenGate`,
  `auth.resolve_mcp`). /solidworks/mcp is a second address early connectors used. Stateless Streamable HTTP; each answer
  is an event stream (`json_response=False`): its headers go at once and sse-starlette sends a comment every 15 s,
  so a tool that waits minutes for SOLIDWORKS survives a proxy's idle limit (Cloudflare in front of bizomat.ai: 524
  after 100 s of silence). Tests read answers with `tests/mcp_reply.rpc`.
- OAuth (`mcpauth.py`): `RESOURCES` maps both paths to "CADOS" with their own protected-resource metadata; a
  token from either works on both; one connection per person and app. DCR, client metadata documents (fetched with
  `safefetch.py`: public https only, pinned address), PKCE S256, refresh rotation, revoke.
- Sign-in (`auth.py`, `accounts.py`, `oauth.py`): accounts with scrypt passwords, invites, Google sign-in (secret
  encrypted with `secretbox.py`), an optional early access code (`OPENSKETCH_ACCESS_CODE` or the owner's setting) that
  makes "Internal tester" accounts. The setup page shows only until the first account exists; after that `/login` is
  Sign in ("Welcome back"), and a person already signed in on that browser (90-day session) goes straight to `next`.
  Sign-in pages and messages never name the OPENSKETCH_* settings. New-account forms (setup, join, sign-up) come with
  a strong password filled in (`auth.suggest_password`, dots with Show, hidden `suggested`); keeping it holds it in
  memory for 30 minutes (`auth.hold_new_password`) so Home shows it once (`GET/DELETE /api/account/new-password`).
  Each account records who chose its password (`pw_by`: self, suggested, owner; `pw_at`), shown on Admin; only the
  scrypt hash is kept, so nobody (the owner included) can read a password back. A member whose password the owner
  set sees "Choose your own in Settings" on Home. No server password anywhere: `auth.mode(scope)` is accounts
  (any account exists), setup (no account and the server is `reachable_by_others()`: OPENSKETCH_PUBLIC_URL on a
  non-loopback host, OPENSKETCH_REQUIRE_SIGNIN, or the legacy OPENSKETCH_PASSWORD still set; or the request is not
  `is_local`: a non-loopback client, any forwarding header, a non-loopback Host (DNS rebinding) or an Origin of
  another site; `mode()` without a scope never reads open) or open (no account, the machine itself only). In
  setup mode only /setup, the product pages and static files answer (no MCP, API, pairing, sign-up, add-in link,
  and no AI app grant made before accounts: "local" grants work only in open mode, "server" ones never without an
  owner); on a server not `reachable_by_others()` /setup itself is taken only from the machine (403 otherwise).
  PasswordGate refuses paths with `.`/`..` segments, `//` or a backslash (400). The first person to submit /setup (name, email, password, "Anyone can create their own account", ticked by default) owns the
  server. OPENSKETCH_PASSWORD is read only as the seed of an old owner's server-wide private address
  (`_legacy_password`). No /reset page: the owner resets people on Admin, and their own password with
  `python -m opensketch --reset-password EMAIL` on the server (`fly ssh console`). Suspension (`accounts.set_suspended`,
  Admin Suspend/Resume, `POST /api/account/users/<id>/suspend`, never the owner): `accounts.get` returns None for a
  suspended account, so sessions, OAuth tokens and refreshes, the private address, the add-in key (`swbridge.resolve`)
  and paired computers (`ACCOUNT_SUSPENDED`, 401; `devicebridge.suspend_person` closes live sessions (409 reason
  suspended) and fails waiting commands; the Companion keeps its pairing and retries) stop at once; OAuth grants are
  kept (refresh says suspended, works again after Resume); sign-in
  (password, Google, Companion password pairing) says it is suspended; `get_any` is for the owner's views.
  `tests/test_mcp_access.py` covers setup mode, per-person MCP, suspension, expiry and no shared password.
- Pages: `/` is the product page for visitors (`site.landing`) and the app's Home for a signed-in person (and on an
  open server); `/overview` (product page) and `/docs` (setup, connection, auth, verify, self test, troubleshooting,
  security) are public (`auth.PUBLIC_PAGES`), as are `/privacy` and the design system under `/ui/` (`cados.css`,
  `app.js`, `og.png`, icons, `kevos-wordmark.svg`). FastAPI's own /docs and /redoc are off. A browser asking for a
  missing page gets the branded 404 (`site.not_found`); API, MCP and device paths keep JSON 404s.
- The signed-in app (`app_pages.py`, one script `static/ui/app.js`, sections in `brand.APP_NAV`): Home (`/dashboard`:
  "Engineering, made intelligent.", a task box that copies the task for the AI assistant and opens Claude or ChatGPT,
  connection summary, a 4-step setup list, recent activity), CAD Assistant (`/assistant`: connector address,
  per-app steps, connected apps with Disconnect, example requests from `catalog.EXAMPLES`), SOLIDWORKS
  (`/solidworks`: installer, computers with default/remove, how CADOS connects (add-in, Companion, cloud MCP,
  self-hosted, direct link, launcher macro: never called an add-in), service address, manual package), Tools
  (`/tools`: every MCP tool in plain words from `catalog.GROUPS`, searchable; `tests/test_app_pages.py` keeps it equal
  to the registered tools), History (`/history`: `GET /api/commands`, the person's commands to paired computers from
  bridge.sqlite; direct-link commands are not recorded), Settings (`/settings`: account, private address and add-in
  key with Show / Copy / New, change password, sign out), Admin (`/admin`, the owner only; anyone else is sent to
  Home: add a person with a suggested password the owner can change, shown once after adding (`POST /api/account/users`, role member), suspend or resume a person, set someone's password
  (`POST /api/account/users/<id>/password`: signs them out everywhere and ends their AI apps' sign-ins), remove a
  person (also revokes their paired computers), people with their computers and AI apps (`GET /api/admin/people`),
  invite links, open sign-up). People sign in with that password when the installer's pairing step opens the
  browser, or type the same email and password in the Companion's pairing window (`POST /v2/devices/pair/password`,
  signed with the pairing key, rate-limited like the sign-in page; the password is sent once and kept nowhere). The
  installer download (`/download/solidworks`) needs sign-in. No Automation section: CADOS keeps no stored automations. Live status
  states: Connected, Disconnected, Checking connection, Authentication required, Installation required, Connection
  error. App header: the sections, a KEVOS menu (kevos.com, Work, CADOS), the person, Sign out; app footer links
  kevos.com and Work. `GET /api/solidworks` still gives the pages everything in one call. Sign-in, consent, notice and
  pairing pages share `auth.PAGE` (product panel and form).
- Server (`server.py`): lifespan (warms the owner's agent CAD worker, runs the MCP session manager), BodyLimit,
  RequestLog, PasswordGate; /healthz; account routes; add-in link (`/mcp/sw/hello|next|result|file|blob`), `/api/sw*`;
  upload links (`/mcp/uploads/{id}`) and artifact downloads (`/mcp/artifacts/...`); OAuth routes; static files
  (favicon, fonts, `static/downloads/BIZOMAT-CAD-SOLIDWORKS.zip` built by the Dockerfile). `/privacy` is public.
- Kernel used by the tools: geometry, features (registry), assembly, naming, params, inspection (sketch DOF via
  `solver/solve_cli.mjs`), measure, preview, importer (STEP), artifacts, uploads, cadworker. `store.py` is the data
  folder and its shared helpers. `docformat.py` is the feature-format text `sw_get_guide` appends and the rebuild
  reports inspection uses.

## SOLIDWORKS add-in and tools

- Shape: AI app -> `/mcp` -> `sw_` tools -> `swbridge` queue -> the add-in long-polls the server over outgoing HTTPS
  and runs each command in SOLIDWORKS. SOLIDWORKS is the master copy; the server keeps no document for it.
- `swbridge.py`: per-person key `oss_...` = HMAC(data secret, person + counter) (`key_for`, `new_key`, `resolve`);
  one session per person (a new hello replaces the old one; 409 with reason restarted / replaced / closed); routes
  `/mcp/sw/hello`, `GET /mcp/sw/next` (held 25 s), `/mcp/sw/result`, `/mcp/sw/file` (gzip bodies),
  `/mcp/sw/blob/{id}`; connected = polled in the last 70 s; a tool waits 240 s by default.
- `sw_tools.py`: features are checked by the registry and each sketch is solved by `solver/solver.js` (over-defined
  refused before sending); `_predict` rebuilds them with the kernel on SOLIDWORKS' current body (STEP) and sends
  `expect` {dv, bbox, tool_bbox, plane, range} per feature; the add-in remakes a feature flipped when SOLIDWORKS read
  the direction the other way. Reading tools run on a STEP of the body, cached per person and part by SOLIDWORKS'
  update stamp. `sw_get_guide` = SW_GUIDE + docformat.GUIDE.
- Drawings (`sw_create_drawing` in `sw_tools.py`, `solidworks/src/Addin/Drawings.cs`): a native .SLDDRW of a saved
  part or assembly from the user's default drawing template, saved next to the model. Sheet A4 to A0 (the
  template's own sheet wins; a note says so), third angle (default, AS 1100) or first angle; the standard views
  (Create3rdAngleViews2 / Create1stAngleViews2) plus an isometric in the free upper right, or named views on a grid;
  the largest preferred scale that fits (from the model's box) unless given; SOLIDWORKS' automatic view scaling is
  turned off while placing views and put back; model dimensions marked for drawing (InsertModelAnnotations3);
  title block fields as the drawing's custom properties. The result lists each view's outline and notes (views off
  the sheet, no dimensions, unsaved model). A half-made drawing is closed. sw_export takes pdf (all sheets), dwg and
  dxf (active sheet) and slddrw from a drawing; sw_preview of a drawing needs screenshot=true. The API calls were
  checked against the SOLIDWORKS 2022 interop (30.5.1). First real run (0.9.0): views placed by SOLIDWORKS fell off
  the sheet at 2:1, and a drawing sheet counted as an open sketch for NotWhileTheUserEdits (now skipped for
  drawings). 0.9.1 sets the views out itself (`ArrangeStandard`: a 25 mm gap from the front view, the group centred
  in the left two thirds above a 65 mm title band, the isometric centred to the right; notes when they do not fit),
  turns on SOLIDWORKS' automatic centre marks and centre lines, auto-arranges each view's dimensions, writes the
  general notes it is sent (`DEFAULT_NOTES`: units, do not scale, deburr, ISO 2768-m) bottom left, and replaces a
  drawing of the same name with overwrite=true. SW_GUIDE has the drafting practice (AS 1100.101/201, ISO 128,
  ISO 129-1) the AI follows: dimension sketches from datums, fewest views, preferred scales, check by screenshot and
  remake. The add-in is 0.10.0
  (`solidworks/Directory.Build.props`; bump it whenever the add-in learns a command). Its hello sends its version and
  the DLL's path; `swbridge.addin_too_old` makes sw_create_drawing, the dwg/dxf/slddrw exports and sw_status
  (`update_needed`) say which add-in is loaded and how to update, before anything is sent. `solidworks.yml` replaces
  the `addin-latest` GitHub release with every main build (private: for the owner). The update message points at
  `swbridge.addin_download()`: `OPENSKETCH_ADDIN_URL`, else this server's own package (`/api/sw/download`).
- Drawing API (0.10.0; `sw_get_drawing`, `sw_edit_drawing` in `sw_tools.py`, `solidworks/src/Addin/DrawingEdits.cs`):
  read the sheet, views (type, orientation, scale, outline in sheet mm, display, dimension count, model) and title
  block fields; change a drawing with up to 40 actions run in order (`DRAWING_ACTIONS` lists each one's keys and is
  checked on the server before anything is sent): view, projected (CreateUnfoldedViewAt3), section (a cutting line
  drawn in the view through a model point via ModelToViewTransform, or a fraction of the outline, then
  CreateSectionViewAt5), detail (a circle, then CreateDetailViewAt4), move, scale (or back to the sheet's), display,
  delete, rename, dimensions (InsertModelAnnotations3 on one view or all), arrange_dimensions, centre_marks
  (AutoInsertCenterMarks2), note (CreateText2), properties, sheet (scale, projection), bom (InsertBomTable4 with the
  first BOM template in SOLIDWORKS' file locations, then AutoBalloon5). A failing action stops the list; the result
  says which, with what was done before it. Not run in a real SOLIDWORKS yet.
- Drafting intelligence (8 Nov 2026; `opensketch/drafting/`, tools in `sw_drafting.py`, docs in the bizomat repository's
  `docs/drafting-intelligence/`): six tools (sw_drafting_analyse, _plan, _build, _check, _knowledge, _feedback) that
  reason over the model and reuse the existing commands for every SOLIDWORKS operation (read, geometry, read_drawing,
  sw_create_drawing, sw_edit_drawing, sw_export): no new add-in API. Modules: facts (OpenCascade, in the CAD worker via
  `engine.recognise_part`), features, understanding (confirmed / inferred / unknown), disciplines (17 labels, override),
  reasoning (per discipline), knowledge (`drafting/knowledge/entries.json`, BM25, company guidelines per account),
  strategy (the plan), dimensioning, standards (AS1100 / ISO / ASME profiles, no standard text, compliance never
  claimed), layout (moves only), qa (100-point index, release blockers apart, `manufacturing_ready` always false),
  learning (SQLite per account in `<data>/drafting/<account>/`), benchmarks (12 synthetic cases, labelled as such).
  Rules: never choose a tolerance, fit, thread, weld, material or finish (TO BE CONFIRMED and a release blocker
  instead); never fill CheckedBy / ApprovedBy; corrections are view moves (from 0.15 also annotation text moves) only;
  the model is never changed (except a fit the designer allows with apply_fits_to_model); feedback
  stays on the server, examples kept only when the person says so. Tests: `tests/test_drafting_engine.py`,
  `tests/test_drafting_tools.py` (simulated SOLIDWORKS: not a live test). Not yet run against a live SOLIDWORKS: the
  live checklist is in TECHNICAL_SPECIFICATION.md, section 8.
- Drafting phase 2 (9 Nov 2026, add-in 0.15.0; `docs/drafting-intelligence/PHASE2_EXECUTION.md` in the bizomat
  repository): `read` with `details` (`solidworks/src/Addin/ModelData.cs`: units, configurations, custom properties,
  material per configuration with `assigned` and the document density, mass properties read in system units and
  converted once by `Core/DrawingMath.cs` with the units stated and a consistency flag, Hole Wizard, cosmetic
  threads, feature parameters, cut list, dimensions with tolerances); `read_drawing` with `annotations`
  (`Addin/DrawingAnnotations.cs`: every annotation with its box in sheet mm, tables); `edit_drawing` actions
  dimension, ordinate, hole_callout, chamfer_dimension, centre_line, centre_mark, move_annotation, tolerance,
  surface_finish, datum, gtol, weld_symbol, revision_table, hole_table, cut_list (`DRAWING_ACTIONS` in sw_tools.py,
  checked first; `DETAILS_FROM` gates them). Rules: engineering values need `confirmed_by`; a tolerance on a model
  dimension needs `model_change=true` (it lives in the part); symbols are SOLIDWORKS objects, never text; a material
  is claimed missing only when the details say `assigned: false`, and never inferred from mass. The drafting tools
  use them when the add-in is 0.15 or later (hole callouts per group, the designer's fits and surface symbols, a
  weldment's cut list; never a weld), and report them as deferred otherwise. Expert reviews
  (`sw_drafting_feedback` submit_for_review, then expert_approve / expert_reject with reviewer_name) are kept apart
  from the 12 synthetic benchmark cases. All compiled and tested against the stand-in only; the live checklist is
  PHASE2_EXECUTION.md section 8, run against a local server (`windows/start.ps1`), with copies of the files.
- `sw_selftest.py`: stages plate / shapes / assembly in `Documents\OpenSketch\selftest` (the plate stage ends with its drawing and a PDF of it), each step ok / check /
  failed with the reason; the first thing to run on a new PC. Tests run it against SimSW, a stand-in add-in built
  on the kernel and mate solver.
- Add-in (`solidworks/`, .NET Framework 4.8 x64, SOLIDWORKS 2022 interop embedded; version in
  `Directory.Build.props`, 0.15.0 on this branch): Core (Json, Geom, SketchPlan, BridgeClient; Bridge2: Crypto (ES256 JWS, JWK),
  Wire (ids, times, 4-byte-length frames), ReplayGuard, PipeLink (the add-in's pipe client: reader thread for pings and
  cancels, one worker for commands, outbox across reconnects, at-most-once by command id), CloudLink and
  CompanionEngine (the Companion's core: signed long poll, verification, routing to a SOLIDWORKS session, spool,
  persistent outbox, heartbeats), Destructive), Addin (Entry: CADOS menu (title CADOS in Tools > Add-Ins), KevosUi CommandManager group and CADOS tab (removes the old KEVOS tab), CadosPane task pane (state, Connect/Disconnect, prompts to copy, confirmation setting, activity, links); Host:
  the direct link and the Companion link, UI-thread snapshot of documents, document events, modal-dialog check,
  Safety confirmation of destructive ops; CompanionPipe: the pipe client that checks its server is the installed
  Companion; ConnectForm; Settings in HKCU\Software\OpenSketch and HKCU\Software\KEVOS\Bridge; Log in
  %LOCALAPPDATA%\OpenSketch\SolidWorks; Commands, Files, Pick, Sketches, Features, Edits with Journal rollback,
  Assembly, ModelData, DrawingAnnotations), App `BIZOMAT-CAD.exe` (Install for me = per-user COM registration + the launcher macro
  `Documents\BIZOMAT CAD\BIZOMAT CAD.swb`; Remove; "Connect to the open SOLIDWORKS" from outside, direct link only).
  The COM ids are unchanged (existing registrations and the macro keep working); the add-in's title is CADOS.
- KEVOS Companion (`solidworks/src/Companion`, `KEVOS.Companion.exe`, net48, compiles Core, no SOLIDWORKS reference):
  tray app, one per Windows user, starts at sign-in (HKLM Run from the MSI; per-user opt-out flag), pairing window,
  device key in CNG (TPM first, not exportable), the pipe `\\.\pipe\KEVOS.Bridge.<SID>` (first instance, user-only
  DACL, remote clients rejected, clients must be SLDWORKS.exe with the installed add-in), SOLIDWORKS detection and the
  LoadAddIn fallback, removal of old per-user OpenSketch registrations, crash restart, logs in
  %LOCALAPPDATA%\KEVOS\Bridge\logs, diagnostics, updater (gateway-signed manifest, hash, Authenticode, same publisher,
  the person asked). `--pair`, `--diagnose`, `--unpair`, `--startup on|off`, `--exit`.
- Installer (`installer/KEVOS-Bridge.wxs`, `installer/build.ps1`): WiX 5 per-machine x64 MSI "BIZOMAT CAD Automation for
  SOLIDWORKS" (UpgradeCode unchanged: upgrades CADOS for SOLIDWORKS and KEVOS Bridge), `BIZOMAT-CAD-Automation-<version>-x64.msi`
  plus the stable `BIZOMAT-CAD-Automation-x64.msi` (and `CADOS-for-SOLIDWORKS-x64.msi`, the 0.12 stable name, as a copy); built and (with secrets) signed by the `installer` job in `solidworks.yml` on Windows;
  releases `bridge-latest` and `bridge-v<version>` (private: the owner downloads from there). Public copies are on
  bizomat.ai: `tools/laptop/cloudflare.ps1 publish installer -File <msi>` puts the versioned and stable names and their
  `.sha256` files in the R2 bucket `bizomat-downloads` (the website Worker serves `/downloads/`). It also writes the
  release record as `/downloads/cad/release.json` and as CAD's `bridge-release.json` in R2. `build.ps1`'s `release.json`
  points there too. `/download/solidworks` (signed in) redirects to OPENSKETCH_INSTALLER_URL, else serves
  `<data>/downloads/BIZOMAT-CAD-Automation-x64.msi` itself when the operator put one there (`server.local_installer`;
  on Fly `/data/downloads/`, because bizomat.ai is still the Fly website, which has no /downloads/ route: the fallback
  below answered 404 on 8 Nov 2026), else redirects to the published `bridge-release.json` msi_url, else
  `https://bizomat.ai/downloads/cad/BIZOMAT-CAD-Automation-x64.msi`. `/download/solidworks.sha256` (the pages'
  checksum link) answers for the file on the volume, else redirects to `brand.checksum_url()`. Pages link the
  checksum (`/download/solidworks.sha256`) and support (`brand.support_url()`: the website's contact page), never GitHub.
  `tests/test_installer.py` keeps the MSI, the add-in code and the download link in step. `build.ps1` signs with a
  store certificate by thumbprint (`-CertThumbprint`/KEVOS_SIGN_THUMBPRINT, never falls back to unsigned when one is
  asked for) or a `.pfx` (CI); `-Timestamp ''` signs without a timestamp, `-NameSuffix` (sign-development passes
  `-DEV` for a self-signed certificate). `sign-development.ps1`: finds or makes the certificate (RSA 3072, 2 years,
  NonExportable), finds SignTool or installs only the SDK Signing Tools (`-SdkSetup`), trusts the public certificate
  for this user (`-TrustOnThisComputer`), builds (`-Build`), signs the three own binaries and the MSI (SHA-256,
  RFC 3161), checks each with `signtool verify /pa` and Get-AuthenticodeSignature, unpacks the MSI (`msiexec /a`) to
  check the files in it, writes `installer/out/signing-report.*` and backs up (`-Backup`). The tests check it never
  exports a private key and the repository holds none. The original 0.13.0 MSI (unsigned, from `bridge-latest`,
  which CI remakes on every build) is in `backups/installer/original/2026-11-07`.

## Hosting

- Code (since 8 Nov 2026): `apps/cad` in the private repository `jogkev-creator/bizomat` (imported from
  `jogkev-creator/CADOS` e669cc6, which is history only). Production: the Fly app `cados`, one Machine in syd with
  1 GB, where this server runs as the `cad` role of `bizomat-entrypoint all` next to Task Management and the proxy
  (the repository root's `fly.toml`, `infrastructure/fly/`, `docs/BIZOMAT-SINGLE-APP.md`); its data is `/data/cad` on
  the volume `opensketch_data`. Deployed only by the root `deploy.yml`, run by hand. Three services only: GitHub Free,
  Fly.io and Cloudflare DNS. The paragraphs below on CADOS's own `fly.toml`, Fly Launch and Cloudflare describe the
  earlier setup and are kept as history.
- Listens on `::` (`--host ::`, `__main__.listen_sockets`: one dual-stack socket, IPv4 alone where there is no IPv6), so
  the BIZOMAT router (Fly app `bizomat`) reaches it over Fly's private network at cados.internal:8080.
- Public address https://bizomat.ai/cad: CAD Automation lives under the BIZOMAT website's own address (the owner's
  decision: everything under bizomat.ai, /cad, /tasks, ...). `canonical.py` (outermost middleware, Host header only):
  a request under the prefix of OPENSKETCH_PUBLIC_URL is served with the prefix taken off the path and put in
  root_path, so routes, the sign-in gate and the computers' signed paths (relative to the gateway address, see
  docs/BRIDGE-PROTOCOL.md) are unchanged; root paths the app writes get the prefix back (HTML href/src/action/url(),
  Location, cookie Path; static/ui/app.js takes it from its own address); pages under the prefix are not gzipped
  by the app (they are rewritten as text). The OAuth metadata of the prefixed resource is served at the root of the
  host (RFC 9728 /.well-known/oauth-protected-resource/cad/mcp, RFC 8414 /.well-known/oauth-authorization-server/cad,
  also /.well-known/openid-configuration/cad); the 401 pointer names the RFC 9728 address and the issuer is
  https://bizomat.ai/cad. On bizomat.ai /CAD 301s to /cad and other pages 302 into /cad (until the website's Worker
  serves the root: it passes /cad/*, the OAuth well-known paths and the root program paths below on to this app). OPENSKETCH_REDIRECT_HOSTS
  (cados.fly.dev, cados.kevos.com, cad.bizomat.ai) are old hosts: pages 301 to https://bizomat.ai/cad, programs
  (/healthz, /mcp*, /solidworks/mcp*, OAuth register/token/revoke, /.well-known/, /v2/, /api/) keep working at their
  root with that host's own address (`canonical.machine_base`), and the consent page accepts a resource on any of
  the server's addresses and answers with that address as `iss`. Every HTML answer carries `server.PAGE_CSP` (`PagePolicy`): scripts only from this server and the two inline
  scripts by hash (`brand.MENU_SCRIPT`, `auth.SHOW_SCRIPT`; a new inline script needs its hash there, and
  `tests/test_canonical.py` crawls every page to check), because the website and Project Management share the
  bizomat.ai origin. Google sign-in comes back under the prefix
  (`auth._request_base` adds root_path): the Google client lists https://bizomat.ai/cad/auth/google/callback. Behind Cloudflare the visitor's address is
  CF-Connecting-IP, believed only from Cloudflare's edge ranges (`auth.CLOUDFLARE_NETS`). Tests:
  `tests/test_canonical.py`, the official MCP client and a paired computer under /cad.
  Favicons (`static/favicon.svg|ico`, `ui/icon-32.png`, `ui/icon-180.png`) are the KEVOS K (drawn from the KEVOS logo;
  kevos.com could not be fetched from the build session). Origin https://cados.fly.dev (Fly
  app `cados`, Sydney, first made with Fly Launch from GitHub on 4 Nov 2026); the deploy health checks use it.
  One deploy source: the app is linked to this repository in Fly (Fly builds and deploys every push to main itself;
  /healthz then reports version "dev", as no commit is passed in). On a push `deploy.yml` only runs the tests (unless
  the repository variable DEPLOY_ON_PUSH is "true"); run by hand it deploys from Actions and makes a missing volume.
  `fly-status.yml` (run by hand, changes nothing) prints the app's machines, volumes, secret
  names, releases, logs and /healthz: both need the repository secret FLY_API_TOKEN (a deploy token for cados).
  No password secret is needed on Fly (fly.toml sets OPENSKETCH_PUBLIC_URL, so a fresh server waits in setup mode);
  an old OPENSKETCH_PASSWORD secret can be unset. The Windows PC server (`windows/`) is the other way to run it.
- fly.toml: app `cados`, performance-1x (one dedicated core, 2 GB), `auto_stop_machines = "suspend"`, kill_timeout 15, volume
  `opensketch_data` at /data. The add-in's long poll keeps the machine awake while SOLIDWORKS is linked.
- `supervisor.py` (`python -m opensketch --supervise`, the image's CMD): asks /healthz every 5 s, restarts the server
  after 120 s without an answer (stacks to the log first), tells a suspended machine from a hang. With
  OPENSKETCH_PERSIST_URL it first restores the data folder from an object store and copies changes back
  (`persist.py`, below).
- Cloudflare Worker and Container hosting (`cloudflare/mcp`, planned Nov 2026, never deployed) was removed on 8 Nov
  2026: CAD MCP runs on the Fly volume. `persist.py` (restore and copy-back of the data folder through an object
  store) stays in the code but is dormant: it runs only when OPENSKETCH_PERSIST_URL is set, which nothing sets.
  `tools/laptop/cloudflare.ps1` is superseded (its README says so).
- `cadworker.py`: CAD in worker processes, one per person and kind, at most OPENSKETCH_CAD_LANES (3) live, one place
  kept for the owner, idle ones stop after 15 min, workers over 800 MB replaced. `OPENSKETCH_CAD_WORKERS=0` runs in
  threads (tests/conftest.py sets it), so `tests/test_cadworker.py` imports every module first in a fresh process and
  runs sw_tools' worker functions in a real worker (a worker's first import is the module of the function it runs).

- One Windows PC (`windows/`): `setup.ps1` (Python 3.12 venv, pinned packages, copies the add-in zip from
  Downloads), `start.ps1` (asks for an optional public https address for a tunnel; no server password; runs on port
  8000), `update-addin.ps1` (newest add-in zip from Downloads, checked >= 0.10.0, into `%LOCALAPPDATA%\BIZOMAT CAD\AddIn`,
  `BIZOMAT-CAD.exe --install` (OpenSketchSW.exe for packages up to 0.13), prints the registered CodeBase and its version), `connect-claude.ps1` (adds the private address to Claude Desktop's config through
  `cmd /c npx mcp-remote`, with a backup, and restarts it), `README.md` (steps: add-in from the Actions artifact, the
  macro, Claude Desktop, Cloudflare Tunnel for web AI apps). The add-in's default address is `http://127.0.0.1:8000` (`Settings.DefaultServer`).
  On Windows the CAD workers lower their priority with psutil (there is no `os.nice`).

## Known limits

- The add-in has been compiled against the SOLIDWORKS 2022 interop and its link tested against a real server; it has
  not yet been run on many real SOLIDWORKS installs. Unconfirmed: SOLIDWORKS listing a per-user (HKCU) add-in at all
  (hence the macro and outside-exe routes), `.swb` macros on every install, AddDimension2 text position, obsolete
  calls kept for 2022 (FeatureFillet3, FeatureLinearPattern5, AddMate5, InsertProtrusionSwept4).
- No prediction for features that name existing SOLIDWORKS features (mirror / pattern of a tree feature). One
  SOLIDWORKS link per person. Equations are written for all configurations. Commands can arrive while SOLIDWORKS
  shows a modal dialog (only an open sketch is detected). SOLIDWORKS run as administrator ignores the per-user
  registration. Plain numbers in equations are in the document's unit.
- Large assemblies are slow to read: each read exports a STEP of the bodies that changed.
- Account admin page (`/admin`) covers people, passwords, invites and open sign-up; early access codes and Google
  sign-in setup are still API only (`/api/account/settings`, `/api/account/google`).
- KEVOS: not yet run on Windows or in a real SOLIDWORKS; the MSI is built only by CI; no MCP progress notifications
  (JSON responses), progress is in `sw_command_status`; ChatGPT and Grok connectors untested; the gateway is one
  process (SQLite, live sessions in memory).
- App sign-in (OAuth) is tested with the MCP Python SDK client; not yet with every AI app's connector.
- The `ai` extra in pyproject.toml (anthropic) is no longer used; drop it the next time the pins are regenerated.

## Next

1. Run the KEVOS checklist (`docs/KEVOS-TEST-REPORT.md` section 4) on Windows with SOLIDWORKS 2022: the MSI, the
   Companion, the add-in's new UI, events, confirmation and modal check have only been compiled, not run.
1. Run the self test on real SOLIDWORKS installs and fix from the reports.
2. Tune SW_GUIDE from what the AI gets wrong on real work.
3. Early access and Google sign-in settings on the Admin page.

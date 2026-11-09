# BIZOMAT CAD Automation for SOLIDWORKS release notes (CADOS for SOLIDWORKS in 0.12, KEVOS Bridge up to 0.11)

## 0.15.0 (BIZOMAT CAD for SOLIDWORKS; built, not yet released or run in SOLIDWORKS)

- Reads the model's details when asked: units, configurations, custom properties, the material per configuration
  (and whether one is assigned), the mass properties with their units and any override, Hole Wizard holes, cosmetic
  threads, feature parameters, the weldment cut list, each dimension once with its tolerance.
- Reads a drawing's annotations when asked: every dimension, note and symbol with its position and size on the
  sheet, and the tables.
- New drawing actions: dimensions between picked edges, ordinate dimensions, hole callouts, chamfer dimensions, centre
  lines and marks, moving an annotation, tolerances and fits, surface texture, datum, GD&T and weld symbols (native
  SOLIDWORKS symbols), revision, hole and cut-list tables. Engineering values only as the designer gave them; a
  tolerance on a model dimension is refused unless the change to the part is confirmed.
- Takes the same commands as 0.14 from a server that does not use these.
- Connect in the BIZOMAT task pane now works like the toolbar's Connect. Before, the pane's button only restarted the
  direct link: a Companion link that was stuck, refused or waiting stayed as it was, and the Companion was not
  started, so people had to use the toolbar button. Both now drop a link that is not connected, start it again at
  once, start the Companion if needed, and never cut a connected link.

## 0.14.0 (BIZOMAT CAD for SOLIDWORKS)

- New name: **BIZOMAT CAD** in Tools > Add-Ins, the toolbar, the task pane, the status window, the installer, the Start
  menu and every message. The COM ids, file names and the MSI's file names are unchanged, so upgrades and the update
  record keep working.
- New folder: **Documents\BIZOMAT CAD** (Documents found through Windows' known-folder API, local or OneDrive) with
  Settings, Projects, Templates, Logs, Cache and Backups. Saves and exports go to Projects, the log to Logs, the
  launcher macro is `BIZOMAT CAD.swb`, working copies go to the Windows temp folder. No OpenSketch folder is made any
  more.
- The old **Documents\OpenSketch** files are copied into Projects once, on the first start: never overwritten (a
  different file of the same name is kept as "name (from OpenSketch)"), never deleted; locked or syncing files are
  copied at a later start. The old folder stays as a backup with a note. Uninstalling never touches Documents.
- Includes 0.13.1 (TLS 1.2 inside SOLIDWORKS).

## 0.13.1 (BIZOMAT CAD Automation for SOLIDWORKS)

- The add-in connects over HTTPS inside SOLIDWORKS. It runs in SLDWORKS.exe and took that program's .NET settings,
  which can leave only TLS 1.0 on; the servers need TLS 1.2, so the add-in's direct link failed with "Could not create
  SSL/TLS secure channel" (found on SOLIDWORKS 2022 SP5), while the Companion connected. The add-in and the Companion
  now always offer TLS 1.2, and leave Windows' own choice alone where it makes it. (Built on the CADOS branch
  claude/practical-lovelace-hi2nio, never merged there; brought into jogkev-creator/bizomat on 8 Nov 2026.)

## 0.13.0 (BIZOMAT CAD Automation for SOLIDWORKS)

- New names, in BIZOMAT's style: the add-in is **BIZOMAT CAD Automation** (Tools > Add-Ins, the **BIZOMAT** tab, menu
  and task pane), the tray app is **BIZOMAT Companion**, and Windows lists **BIZOMAT CAD Automation for SOLIDWORKS**
  by BIZOMAT. The Start menu folder is BIZOMAT: BIZOMAT Companion, Pair this computer with CAD Automation, CAD
  Automation diagnostics, Remove this computer from CAD Automation.
- The new BIZOMAT logo everywhere: a B whose lower counter is a teal forward arrow (work that moves on by itself), on
  a navy tile. It is the Companion's tray icon (with its status dot), the add-in's tab, toolbar and task pane, the
  programs' icon (Start menu, Apps list, taskbar, Explorer) and, new, the add-in's icon in Tools > Add-Ins. The old
  KEVOS and CADOS tabs are removed when found.
- A clear file name: **BIZOMAT-CAD-Automation-x64.msi** (and `BIZOMAT-CAD-Automation-<version>-x64.msi` per release).
  The 0.12 name, `CADOS-for-SOLIDWORKS-x64.msi`, is still published as a copy so links already given out keep working.
- A computer paired with an earlier address of CAD Automation (cados.kevos.com, cados.fly.dev, cad.bizomat.ai) moves to
  https://bizomat.ai/cad when the Companion starts, and stays paired: the same server, the same pairing.
- Install it over any earlier version: it upgrades CADOS for SOLIDWORKS and KEVOS Bridge in place. Every id stays (the
  COM classes, files, pipe, keys, registry and data folders), so the computer stays paired and its settings stay.

## 0.12.3 (CADOS for SOLIDWORKS; test build)

- CAD Automation's address is https://bizomat.ai/cad. The Companion's pairing window suggests it when no address
  was set, the task pane links there until the computer is paired, and the installer's help link opens its
  documentation. Computers paired with https://cados.kevos.com keep that address and keep working.
- Uninstalling removes the add-in's and the launcher's COM registration completely (0.12.2 left two empty keys).

## 0.12.2 (CADOS for SOLIDWORKS; test build)

- Pair with your CADOS email and password: the pairing window takes the same email and password you sign in to
  CADOS with, and adds the computer at once (the password is sent once and kept nowhere). Leaving them empty keeps the
  browser step.
- The Companion speaks of your CADOS account ("CADOS address", "Pause CADOS").

## 0.12.1 (CADOS for SOLIDWORKS; test build)

- The task pane, toolbar icons and links use the KEVOS colours of kevos.com (accent #c2410c, ink #1c1b19, paper
  #fbfaf7). No change to commands or the link.

## 0.12.0 (CADOS for SOLIDWORKS; test build, see the test report)

- **CADOS by KEVOS.** The add-in is listed in Tools > Add-Ins as **CADOS**; its CommandManager tab, toolbar and menu
  are **CADOS** (the old KEVOS tab is removed when found). The installer is **CADOS for SOLIDWORKS**
  (`CADOS-for-SOLIDWORKS-<version>-x64.msi`, and `CADOS-for-SOLIDWORKS-x64.msi` on the latest build); it upgrades
  KEVOS Bridge 0.11 in place (same UpgradeCode), keeping settings and pairing.
- **CADOS task pane** in SOLIDWORKS: connection state, Connect / Disconnect, prompts to copy into your AI assistant,
  the confirmation setting, live activity, and links to the dashboard, documentation, troubleshooting, the Companion
  and the log.
- The confirmation window is **CADOS: confirm**. Messages from the add-in and the Companion name CADOS.
- The Companion's pairing window suggests `https://cados.kevos.com` when no address was set.
- Website: **Download CADOS for SOLIDWORKS** (`/download/solidworks`), the installation guide, system requirements and
  supported SOLIDWORKS versions.

Kept: COM ids and ProgIDs, the per-user installer, the direct link, the launcher macro (fallback only), every tool.

Known limits: not yet run in a real SOLIDWORKS (test report section 4); the MSI is unsigned until a signing service
is connected.


## 0.11.0 (first KEVOS Bridge release; test build, see the test report)

Install once, register once, then: open SOLIDWORKS and ask your AI app. No command prompt, no macro, no address or
key to paste.

New:
- **KEVOS Companion** (`KEVOS.Companion.exe`): a tray app that starts with Windows, registers the computer (pairing
  with a short code on the KEVOS website), keeps the signed link to the KEVOS server, reconnects by itself, detects
  SOLIDWORKS and the add-in, can pause, checks for verified updates, and writes diagnostics.
- **Registered computers** on the server: several per account, each with its own key; choose with `device=`, a
  default, or automatically when only one has SOLIDWORKS open. Home page section **Your computers**.
- **Protocol 2** (`docs/BRIDGE-PROTOCOL.md`): signed commands and device requests, acknowledgments, progress,
  results with chunked files, cancellation, expiry, at-most-once execution, heartbeats.
- **Add-in 0.11.0**: KEVOS menu, toolbar and CommandManager tab; status of the Companion and computer; connects to the
  Companion by itself (starting it when needed); document events; refuses to run inside an open dialog; asks the
  person before destructive changes; long batches, feature lists and drawing edits can be cancelled between steps.
- **Tools**: `sw_list_devices`, `sw_command_status`, `sw_cancel_command`; every SOLIDWORKS tool takes `device`;
  errors carry `error_code`.
- **Installer**: one signed MSI (WiX) for all users, upgrade, repair and uninstall that keep settings and CAD files;
  CI builds it on Windows.

Kept: every existing tool, its arguments and results; the direct add-in link (address and key) and the launcher
macro as fallbacks; the add-in's COM ids, so existing registrations keep working.

Changed: the add-in's title in Tools > Add-Ins is now KEVOS; its menu is Tools > KEVOS.

Known limits: not yet run in a real SOLIDWORKS or on Windows by the build (see `docs/KEVOS-TEST-REPORT.md`);
ChatGPT and Grok connectors not yet tried; MCP progress notifications are not sent (progress is in
`sw_command_status`); SOLIDWORKS run as administrator is not supported.

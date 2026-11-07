# bizomat-mcp: CAD Automation on Cloudflare

The Worker in front of CAD Automation's server. The server is the Python app in this repository, unchanged, running
as a Cloudflare Container built from the repository's `Dockerfile`. One instance, named `main`, holds the live
sessions with the computers.

```
AI apps        https://mcp.bizomat.ai/mcp ─┐
Pages, sign-in https://bizomat.ai/cad/...  ─┼─> Worker bizomat-mcp ─> Durable Object CadServer ─> Container (port 8080)
Computers      https://bizomat.ai/cad/v2/ ─┘     (website Worker bizomat hands /cad/... here by service binding)
                                                         │
                         http://persist.bizomat.internal ┴─> R2 bucket bizomat-mcp-data (data/<file>)
```

## Addresses

- MCP: `https://mcp.bizomat.ai/mcp` (OAuth issuer `https://mcp.bizomat.ai`) and `https://bizomat.ai/cad/mcp`
  (issuer `https://bizomat.ai/cad`). A connection made at either keeps working.
- Pages: `https://bizomat.ai/cad`. A page asked for on mcp.bizomat.ai answers 301 there.
- Computers (Companion 0.13 and later): `https://bizomat.ai/cad/v2/...`. The earlier hosts in
  `OPENSKETCH_REDIRECT_HOSTS` (cados.kevos.com, cad.bizomat.ai) keep working for programs if their DNS is pointed here.
- `/__worker/health`: the Worker alone, without starting the container.
- No workers.dev address: the first deploy creates the mcp.bizomat.ai record and its certificate.

The Worker sets `X-Forwarded-Proto` and `X-Forwarded-Host` from the address the visitor used (`src/settings.ts`
`forServer`), replacing anything a client sent. The server builds its OAuth addresses, cookie flags and same-site
checks from them. The visitor's address is `CF-Connecting-IP`, set by Cloudflare's edge.

## Data

Container disks start empty after every sleep, restart or deploy. The server's supervisor (`opensketch/persist.py`):

- restores the data folder from R2 before the server starts;
- does not start the server when R2 holds no accounts (`data/accounts.enabled`), so an empty server is never offered
  for set-up to whoever comes first. Visitors get 503 until the data is moved;
- copies every changed state file back every 2 s, and once more after the server stops (Cloudflare sends SIGTERM and
  waits up to 15 minutes).

The container reaches R2 only through the Worker's outbound handler (`src/persist.ts`): no R2 keys in the container.
Bodies stream; R2 checks each upload against its SHA-256, so a torn upload never replaces a good copy.

## Settings

`wrangler.jsonc` `vars` set the addresses. `OPENSKETCH_ACCESS_CODE` and `OPENSKETCH_INSTALLER_URL` are optional
(`wrangler secret put OPENSKETCH_ACCESS_CODE`). `OPENSKETCH_VERSION` is passed at deploy. The server's own settings
(Google sign-in, invites, open sign-up) are in its data, as before.

## Pause

`CAD_PAUSED=1`, a Worker secret so that it changes without a new image (`wrangler secret put CAD_PAUSED`, removed with
`wrangler secret delete CAD_PAUSED`):
- every path but `/__worker/health` answers 503 "paused for maintenance";
- a running server is stopped with SIGTERM, so it copies its last changes to R2 first;
- nothing starts it again until the pause is lifted.
The health answer says `"paused": true`. It is used when a new copy of the data goes over one already in R2
(`cloudflare.ps1 move cad -Replace`), so the server cannot write over it.

## Deploy

Needs the Workers Paid plan and Docker on the machine that deploys (wrangler builds the image).

```bash
npm ci
npm run check
npx wrangler deploy --var OPENSKETCH_VERSION:$(git rev-parse --short HEAD)
```

The owner's laptop does this with `.\cloudflare.ps1 deploy mcp` (`tools/laptop/cloudflare.ps1`, next to bizomat.ps1).
That script has the whole move in order:
1. `check`.
2. `deploy mcp`, `deploy tasks`, `deploy website`.
3. `secrets website`.
4. `move tasks`, then `move cad`.
5. `switch`: the DNS steps, which stay the owner's.
6. `status`.

## Local run

With Docker running, `npx wrangler dev` builds the image and runs the Worker, the container and a local R2. An
empty local R2 gives 503, as in production. Seed it with a data folder, file by file:

```bash
npx wrangler r2 object put bizomat-mcp-data/data/users.json --file ./data/users.json --local
```

`wrangler dev` sends every request to the host of the route in `wrangler.jsonc` and rewrites `https://` in response
headers to `http://`. Remove the route to try other hosts, and read addresses in responses with that in mind.

## Tests

`npm run check`: typecheck and vitest. `test/contract.test.ts` runs the server's own client (`opensketch/persist.py`,
through `python3`) against `src/persist.ts` over HTTP.

## Limits

- One instance (`max_instances: 1`). It sleeps after 30 minutes without a request; a paired Companion's long poll
  (every 25 s) keeps it awake. A cold start restores the data first (about 3 s for a small data folder in a local run).
- A state file over 64 MiB is not copied (the supervisor logs it). `bridge.sqlite` grows with the command history.
- A container killed without SIGTERM loses at most the last 2 s of changes.
- Files in transit (uploads, exports for download, computers' file chunks) are not kept across a restart. Export
  links last an hour on a server that stays up.

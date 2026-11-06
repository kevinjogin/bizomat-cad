// What the Worker tells CAD Automation's server when it starts the container, and how it hands requests on.
// Kept apart from index.ts (which needs the Workers runtime) so the tests run on Node.

import { PERSIST_HOST } from './persist';

/** Worker variables passed to the server as they are (wrangler.jsonc "vars", and --var at deploy). */
export const PASSED = [
  'OPENSKETCH_PUBLIC_URL',
  'OPENSKETCH_MCP_URL',
  'OPENSKETCH_REDIRECT_HOSTS',
  'OPENSKETCH_ALIAS_HOSTS',
  'OPENSKETCH_ACCESS_CODE',
  'OPENSKETCH_INSTALLER_URL',
  'OPENSKETCH_VERSION',
] as const;

/** The server's environment inside the container. */
export function serverEnv(env: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {
    OPENSKETCH_DATA: '/data',
    // the data folder lives in R2 (opensketch/persist.py); the server does not start without its accounts there
    OPENSKETCH_PERSIST_URL: `http://${PERSIST_HOST}`,
    // only this Worker reaches the container, and Cloudflare's edge sets CF-Connecting-IP on every request
    OPENSKETCH_CLIENT_IP_HEADER: 'cf-connecting-ip',
  };
  for (const k of PASSED) {
    const v = env[k];
    if (typeof v === 'string' && v.trim()) out[k] = v.trim();
  }
  return out;
}

/**
 * The request as the server should see it. The Worker states the scheme and host the visitor used (the request's own
 * URL: https://mcp.bizomat.ai/..., or https://bizomat.ai/cad/... from the website Worker), replacing whatever a client
 * sent, because the server builds its OAuth addresses, cookie flags and same-site checks from them (opensketch/auth.py
 * public_url, _secure, _request_base, the Origin check; mcpauth.py base_url).
 */
export function forServer(request: Request): Request {
  const url = new URL(request.url);
  const headers = new Headers(request.headers);
  headers.set('x-forwarded-proto', url.protocol === 'https:' ? 'https' : 'http');
  headers.set('x-forwarded-host', url.host);
  return new Request(request, { headers });
}

/** The Worker's own health answer, without starting the container (monitoring and the laptop's checks). */
export const WORKER_HEALTH = '/__worker/health';

/** What a visitor gets while the container cannot be started (a deploy in progress, or no data in R2 yet). */
export function unavailable(detail: string): Response {
  return new Response(
    JSON.stringify({ error: 'CAD Automation is starting or unavailable. Try again in a minute.', detail }),
    { status: 503, headers: { 'content-type': 'application/json', 'retry-after': '30', 'cache-control': 'no-store' } },
  );
}

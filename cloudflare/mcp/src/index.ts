// bizomat-mcp: the Cloudflare Worker in front of CAD Automation's server (https://mcp.bizomat.ai/mcp).
//
// The server (the Python app in this repository: MCP over Streamable HTTP with OAuth 2.1, the pages, the SOLIDWORKS
// computers' link) needs an OpenCascade CAD kernel, worker processes and files on disk, so it runs unchanged as a
// Cloudflare Container built from the repository's Dockerfile. This Worker hands every request to the one instance,
// through its Durable Object, and gives the container its data store on R2 (src/persist.ts). The website Worker
// (bizomat, gocore-website) hands bizomat.ai/cad/... here by service binding, so the old addresses keep working.
//
// One instance only ("main"): the server keeps live sessions with the computers in memory and is the only writer of
// its data. It sleeps after 30 minutes without a request; a paired Companion's long poll (every 25 s) keeps it awake.

import { Container, ContainerProxy, getContainer } from '@cloudflare/containers';
import { handlePersist, PERSIST_HOST } from './persist';
import { forServer, serverEnv, unavailable, WORKER_HEALTH } from './settings';

export { ContainerProxy }; // outbound interception (the data store) needs it exported

export interface Env {
  CAD: DurableObjectNamespace<CadServer>;
  DATA: R2Bucket;
  OPENSKETCH_PUBLIC_URL?: string;
  OPENSKETCH_MCP_URL?: string;
  OPENSKETCH_REDIRECT_HOSTS?: string;
  OPENSKETCH_ALIAS_HOSTS?: string;
  OPENSKETCH_ACCESS_CODE?: string;
  OPENSKETCH_INSTALLER_URL?: string;
  OPENSKETCH_VERSION?: string;
}

const PORT = 8080;
// Restoring the data folder from R2 and starting Python with the CAD kernel takes longer than the class's default
// 20 s port wait.
const START_WAIT_MS = 180_000;

export class CadServer extends Container<Env> {
  defaultPort = PORT;
  sleepAfter = '30m';
  enableInternet = true; // Google sign-in, AI apps' client metadata documents, GitHub release downloads
  pingEndpoint = 'localhost/healthz';

  constructor(ctx: ConstructorParameters<typeof Container>[0], env: Env) {
    super(ctx, env);
    this.envVars = serverEnv(env as unknown as Record<string, unknown>);
  }

  override async fetch(request: Request): Promise<Response> {
    if (!this.ctx.container?.running) {
      try {
        await this.startAndWaitForPorts({ ports: PORT, cancellationOptions: { portReadyTimeoutMS: START_WAIT_MS } });
      } catch (e) {
        console.error('CAD Automation did not start', e);
        return unavailable('the server did not start; its log is in the Worker logs');
      }
    }
    return this.containerFetch(request, PORT);
  }

  override onStop({ exitCode, reason }: { exitCode: number; reason: string }) {
    // exit code 2: the supervisor refused to start without its data in R2 (opensketch/persist.py)
    console.log('CAD Automation stopped', { exitCode, reason });
  }
}

CadServer.outboundByHost = {
  [PERSIST_HOST]: (request: Request, env: Env) => handlePersist(request, env.DATA),
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === WORKER_HEALTH) {
      return Response.json({ ok: true, worker: 'bizomat-mcp', version: env.OPENSKETCH_VERSION ?? 'dev' },
        { headers: { 'cache-control': 'no-store' } });
    }
    try {
      return await getContainer(env.CAD, 'main').fetch(forServer(request));
    } catch (e) {
      console.error('bizomat-mcp could not reach the container', e);
      return unavailable('the container could not be reached');
    }
  },
} satisfies ExportedHandler<Env>;

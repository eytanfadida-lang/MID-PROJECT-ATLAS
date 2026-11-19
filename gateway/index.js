// Entry point: `node index.js`. Configuration (environment variables):
//   ATLAS_URL            base URL of the Atlas app, e.g. https://eytan1985.pythonanywhere.com   (required)
//   GATEWAY_TOKEN_FILE   file holding the shared token (default ../.gateway_token, created by the app)
//   GATEWAY_TOKEN        the token itself (overrides the file)
//   AUTH_DIR             where WhatsApp logins are stored (default ./auth - keep it private!)
//   POLL_MS              how often to ask the app what to do (default 3000)
//   GATEWAY_FAKE=1       use fake sessions (no WhatsApp) to try the UI
//   FAKE_INCOMING_MS     (fake mode) deliver one test message this many ms after connecting
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Gateway, createApi } from './gateway.js';

const here = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.ATLAS_URL || '').replace(/\/+$/, '');
if (!baseUrl) {
  console.error('ATLAS_URL is required, e.g. ATLAS_URL=https://your-user.pythonanywhere.com');
  process.exit(1);
}
const tokenFile = resolve(here, process.env.GATEWAY_TOKEN_FILE || '../.gateway_token');
const getToken = () => {
  if (process.env.GATEWAY_TOKEN) return process.env.GATEWAY_TOKEN;
  try {
    return readFileSync(tokenFile, 'utf8').trim();
  } catch {
    stamp(`token file not found yet: ${tokenFile} (the app creates it on start; retrying)`);
    return '';
  }
};
const stamp = (...a) => console.log(new Date().toISOString(), ...a);
const pollMs = Number(process.env.POLL_MS || 3000);
const authDir = resolve(here, process.env.AUTH_DIR || './auth');

const api = createApi({ baseUrl, getToken });
let createSession;
if (process.env.GATEWAY_FAKE === '1') {
  const { createFakeSessionFactory } = await import('./fake_session.js');
  createSession = createFakeSessionFactory({
    scanAfterMs: Number(process.env.FAKE_SCAN_AFTER_MS || 15000),
    incomingAfterMs: Number(process.env.FAKE_INCOMING_MS || 0),
    log: stamp,
  });
  stamp('FAKE mode: no WhatsApp connection will be made');
} else {
  const { createBaileysSessionFactory } = await import('./session.js');
  createSession = createBaileysSessionFactory({ authDir, api, log: stamp });
}

const gateway = new Gateway({ api, createSession, log: stamp });

let stopping = false;
async function loop() {
  let failures = 0;
  while (!stopping) {
    try {
      const startedAt = Date.now();
      await gateway.tick();
      const took = Date.now() - startedAt;
      // The app treats the gateway as offline if it has not polled for 30s: make slow passes visible in the log
      if (took > 5000) stamp(`slow pass: ${took}ms`);
      failures = 0;
    } catch (e) {
      failures += 1;
      // The app being briefly unreachable (reload, deploy) is normal: keep running, back off up to 30s
      stamp(`poll failed (${failures}): ${e.message}`);
    }
    // The app says how soon to come back (fast while there is activity, slow when idle); POLL_MS overrides it.
    const base = process.env.POLL_MS ? pollMs : gateway.nextPollMs || pollMs;
    await new Promise((r) => setTimeout(r, Math.min(base * (1 + failures), 30000)));
  }
}

for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, async () => {
    stopping = true;
    stamp(`${signal}: stopping sessions (logins are kept)`);
    await gateway.stopAll();
    process.exit(0);
  });
}
stamp(`gateway started, app: ${baseUrl}`);
loop();

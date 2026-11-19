// Core of the gateway: keeps one "session" (a linked WhatsApp device) per account that the Atlas app asks for.
//
// The app never talks to this process directly (a PythonAnywhere always-on task cannot receive HTTP).
// Instead this loop polls the app (GET /gateway/accounts), reconciles what the admin asked for ("desired") with the
// sessions it is running, sends the messages waiting in the outbox, and reports back (status / QR / phone / received
// messages / delivery receipts / send results) over the same authenticated HTTP API.
//
// `createSession(account, report, events)` is injected so the loop can be tested with fake sessions (see test/).
// A session must implement: start(), stop() (keep login), logout() (unlink + wipe login),
// isConnected(), send(item) -> { wamid }, and call report({ status, ... }) / events.messages([...]) /
// events.receipts([...]) whenever something happens.

const SEND_GAP_MS = [800, 1800]; // pause between consecutive sends from one batch: bursts look robotic to WhatsApp
export const SEND_TIMEOUT_MS = 45000; // a send that takes longer is reported as failed (it may still go out)
const MAX_PENDING_REPORTS = 500;

export class Gateway {
  constructor({
    api, createSession, log = console.log, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), random = Math.random,
    backgroundSends = true, sendTimeoutMs = SEND_TIMEOUT_MS,
  }) {
    this.api = api;
    this.createSession = createSession;
    this.log = log;
    this.sleep = sleep;
    this.random = random;
    this.sessions = new Map(); // account id -> session
    this.lastReported = new Map(); // account id -> JSON of last status report (skip exact duplicates)
    this.pendingReports = []; // messages/receipts/send results that could not be delivered to the app yet
    this.nextPollMs = null; // the app tells us how soon to come back (fast when busy)
    this.backgroundSends = backgroundSends; // sends run beside the polling loop, so a slow send never stops the heartbeat
    this.sendTimeoutMs = sendTimeoutMs;
    this.outboxQueue = [];
    this.draining = null;
  }

  // Deliver something to the app; if the app is unreachable keep it and retry on the next pass (bounded).
  async deliver(label, fn) {
    this.pendingReports.push({ label, fn });
    if (this.pendingReports.length > MAX_PENDING_REPORTS) this.pendingReports.shift();
    await this.flush();
  }

  async flush() {
    while (this.pendingReports.length) {
      const next = this.pendingReports[0];
      try {
        await next.fn();
      } catch (e) {
        this.log(`delivery pending (${next.label}): ${e.message}`);
        return;
      }
      this.pendingReports.shift();
    }
  }

  async report(id, payload) {
    const key = JSON.stringify(payload);
    if (this.lastReported.get(id) === key) return;
    this.lastReported.set(id, key);
    try {
      await this.api.reportState(id, payload);
    } catch (e) {
      this.lastReported.delete(id); // retry next time the state is reported
      this.log(`report failed for #${id}: ${e.message}`);
    }
  }

  eventsFor(id) {
    return {
      messages: (items) => this.deliver(`messages #${id}`, () => this.api.reportMessages(id, items)),
      receipts: (updates) => this.deliver(`receipts #${id}`, () => this.api.reportReceipts(id, updates)),
    };
  }

  // One pass: sync with the app, reconcile sessions, send the outbox. Returns the number of accounts listed.
  async tick() {
    await this.flush();
    const { accounts, outbox = [], poll_ms: pollMs } = await this.api.sync();
    if (pollMs) this.nextPollMs = pollMs;
    const listed = new Set(accounts.map((a) => a.id));

    for (const account of accounts) {
      const session = this.sessions.get(account.id);
      if (session && session.dead) {
        this.sessions.delete(account.id);
      }
      const live = this.sessions.get(account.id);

      if (account.desired === 'delete') {
        await this.remove(account.id, live);
        await this.report(account.id, { status: 'deleted' });
        continue;
      }

      if (account.desired === 'disconnect') {
        if (live) {
          await live.stop();
          this.sessions.delete(account.id);
        }
        if (account.status !== 'disconnected') {
          await this.report(account.id, { status: 'disconnected' });
        }
        continue;
      }

      // desired === 'connect'
      if (live) continue;
      // The phone removed this device: wait for the admin to press "connect" again (the app then resets the status).
      if (account.status === 'logged_out') continue;
      this.lastReported.delete(account.id);
      const created = this.createSession(account, (payload) => this.report(account.id, payload), this.eventsFor(account.id));
      this.sessions.set(account.id, created);
      this.log(`starting session #${account.id} (${account.label})`);
      await created.start();
    }

    // Accounts that disappeared from the app (deleted while this process was down): unlink and clean up.
    for (const [id, session] of this.sessions) {
      if (!listed.has(id)) {
        await this.remove(id, session);
      }
    }

    const drained = this.sendOutbox(outbox);
    if (!this.backgroundSends) await drained;
    return accounts.length;
  }

  // Queue the items and make sure one drain loop is running. Returns the promise of that loop.
  sendOutbox(items) {
    this.outboxQueue.push(...items);
    if (!this.draining && this.outboxQueue.length) {
      this.draining = this.drain().finally(() => {
        this.draining = null;
      });
    }
    return this.draining || Promise.resolve();
  }

  async drain() {
    let first = true;
    while (this.outboxQueue.length) {
      const item = this.outboxQueue.shift();
      if (!first) {
        const [min, max] = SEND_GAP_MS;
        await this.sleep(min + this.random() * (max - min));
      }
      first = false;
      const session = this.sessions.get(item.account_id);
      let result;
      if (!session || !session.isConnected()) {
        result = { ok: false, error: 'החשבון לא מחובר' };
      } else {
        try {
          const sent = await this.withTimeout(session.send(item), this.sendTimeoutMs);
          result = { ok: true, wamid: sent?.wamid || null };
        } catch (e) {
          this.log(`send #${item.id} failed: ${e.message}`);
          result = { ok: false, error: e.message };
        }
      }
      await this.deliver(`send result #${item.id}`, () => this.api.reportResult(item.id, result));
    }
  }

  withTimeout(promise, ms) {
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('השליחה לוואטסאפ לא הסתיימה בזמן - ייתכן שההודעה לא נשלחה')), ms);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
  }

  async remove(id, session) {
    if (session) {
      try {
        await session.logout();
      } catch (e) {
        this.log(`logout failed for #${id}: ${e.message}`);
      }
      this.sessions.delete(id);
    }
    this.lastReported.delete(id);
  }

  async stopAll() {
    for (const session of this.sessions.values()) {
      try {
        await session.stop();
      } catch (e) {
        this.log(`stop failed: ${e.message}`);
      }
    }
    this.sessions.clear();
  }
}

// HTTP client for the Atlas gateway API (/gateway/*). `getToken` is called again after a 401 so a
// regenerated token file is picked up without restarting the process.
export const REQUEST_TIMEOUT_MS = 20000;

export function createApi({ baseUrl, getToken, fetchImpl = fetch, timeoutMs = REQUEST_TIMEOUT_MS }) {
  let token = getToken();
  async function request(path, options = {}, retry = true) {
    // A request that hangs would freeze the whole polling loop (and the heartbeat the app uses to tell the gateway is alive)
    const response = await fetchImpl(`${baseUrl}${path}`, {
      ...options,
      signal: AbortSignal.timeout(timeoutMs),
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    if (response.status === 401 && retry) {
      token = getToken();
      return request(path, options, false);
    }
    if (!response.ok) throw new Error(`${options.method || 'GET'} ${path} -> HTTP ${response.status}`);
    return response.json();
  }
  const post = (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) });
  return {
    async sync() {
      return request('/gateway/accounts');
    },
    async reportState(id, payload) {
      return post(`/gateway/accounts/${id}/state`, payload);
    },
    async reportMessages(id, messages) {
      return post(`/gateway/accounts/${id}/messages`, { messages });
    },
    async reportReceipts(id, updates) {
      return post(`/gateway/accounts/${id}/receipts`, { updates });
    },
    async reportResult(outboxId, result) {
      return post(`/gateway/outbox/${outboxId}/result`, result);
    },
    // Fetch an attachment the admin uploaded in the app (public static file) so it can be sent through WhatsApp.
    async downloadAttachment(path) {
      const response = await fetchImpl(`${baseUrl}${path}`, { signal: AbortSignal.timeout(timeoutMs * 3) });
      if (!response.ok) throw new Error(`GET ${path} -> HTTP ${response.status}`);
      return Buffer.from(await response.arrayBuffer());
    },
  };
}

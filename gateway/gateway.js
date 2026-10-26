// Core of the gateway: keeps one "session" (a linked WhatsApp device) per account that the Atlas app asks for.
//
// The app never talks to this process directly (a PythonAnywhere always-on task cannot receive HTTP).
// Instead this loop polls the app every few seconds, reconciles what the admin asked for ("desired") with
// the sessions it is running, and reports back (status / QR / phone) over the same authenticated HTTP API.
//
// `createSession(account, report)` is injected so the loop can be tested with fake sessions (see test/).
// A session must implement: start(), stop() (keep login), logout() (unlink + wipe login), and call
// report({ status, qr_image?, qr_ttl?, phone?, error? }) whenever something changes.

export class Gateway {
  constructor({ api, createSession, log = console.log }) {
    this.api = api;
    this.createSession = createSession;
    this.log = log;
    this.sessions = new Map(); // account id -> session
    this.lastReported = new Map(); // account id -> JSON of last report (skip exact duplicates)
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

  // One reconciliation pass. Returns the number of accounts the app listed.
  async tick() {
    const accounts = await this.api.listAccounts();
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
      const created = this.createSession(account, (payload) => this.report(account.id, payload));
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
    return accounts.length;
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
export function createApi({ baseUrl, getToken, fetchImpl = fetch }) {
  let token = getToken();
  async function request(path, options = {}, retry = true) {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      ...options,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    if (response.status === 401 && retry) {
      token = getToken();
      return request(path, options, false);
    }
    if (!response.ok) throw new Error(`${options.method || 'GET'} ${path} -> HTTP ${response.status}`);
    return response.json();
  }
  return {
    async listAccounts() {
      return (await request('/gateway/accounts')).accounts;
    },
    async reportState(id, payload) {
      return request(`/gateway/accounts/${id}/state`, { method: 'POST', body: JSON.stringify(payload) });
    },
  };
}

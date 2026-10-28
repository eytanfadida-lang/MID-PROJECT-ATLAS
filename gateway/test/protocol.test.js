// Unit tests for the reconciliation loop (no network, no WhatsApp): `npm test`
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Gateway, createApi } from '../gateway.js';

function makeHarness(initialAccounts, { outbox = [] } = {}) {
  const accounts = new Map(initialAccounts.map((a) => [a.id, { status: 'starting', desired: 'connect', label: `a${a.id}`, ...a }]));
  const reports = [];
  const results = [];
  const messages = [];
  const sessions = [];
  let pendingOutbox = [...outbox];
  let down = false;
  const api = {
    async sync() {
      if (down) throw new Error('app down');
      const out = pendingOutbox;
      pendingOutbox = [];
      return { accounts: [...accounts.values()].map((a) => ({ ...a })), outbox: out, poll_ms: 1000 };
    },
    async reportState(id, payload) {
      reports.push([id, payload]);
      const a = accounts.get(id);
      if (!a) return;
      if (payload.status === 'deleted') accounts.delete(id);
      else a.status = payload.status;
    },
    async reportMessages(id, items) {
      if (down) throw new Error('app down');
      messages.push([id, items]);
    },
    async reportReceipts() {},
    async reportResult(id, result) {
      if (down) throw new Error('app down');
      results.push([id, result]);
    },
  };
  const createSession = (account, report, events) => {
    const s = { id: account.id, started: 0, stopped: 0, loggedOut: 0, dead: false, connected: true, report, events, sent: [] };
    s.start = async () => { s.started += 1; };
    s.stop = async () => { s.stopped += 1; };
    s.logout = async () => { s.loggedOut += 1; };
    s.isConnected = () => s.connected;
    s.send = async (item) => { if (/boom/.test(item.body)) throw new Error('boom'); s.sent.push(item); return { wamid: `W${item.id}` }; };
    sessions.push(s);
    return s;
  };
  const gateway = new Gateway({ api, createSession, log: () => {}, sleep: async () => {}, random: () => 0 });
  return { gateway, accounts, reports, sessions, results, messages, setDown: (v) => { down = v; }, queueOutbox: (items) => { pendingOutbox.push(...items); } };
}

test('starts one session per account that should be connected, only once', async () => {
  const h = makeHarness([{ id: 1 }, { id: 2 }]);
  await h.gateway.tick();
  await h.gateway.tick();
  assert.equal(h.sessions.length, 2);
  assert.deepEqual(h.sessions.map((s) => s.started), [1, 1]);
});

test('disconnect stops the session (keeps the login) and reports once', async () => {
  const h = makeHarness([{ id: 1 }]);
  await h.gateway.tick();
  h.accounts.get(1).desired = 'disconnect';
  await h.gateway.tick();
  await h.gateway.tick();
  assert.equal(h.sessions[0].stopped, 1);
  assert.equal(h.sessions[0].loggedOut, 0);
  assert.deepEqual(h.reports.filter(([, p]) => p.status === 'disconnected').length, 1);
});

test('delete logs out, reports deleted, and forgets the account', async () => {
  const h = makeHarness([{ id: 1 }]);
  await h.gateway.tick();
  h.accounts.get(1).desired = 'delete';
  await h.gateway.tick();
  assert.equal(h.sessions[0].loggedOut, 1);
  assert.ok(h.reports.some(([id, p]) => id === 1 && p.status === 'deleted'));
  assert.equal(h.accounts.has(1), false);
  assert.equal(h.gateway.sessions.size, 0);
});

test('delete of an account with no running session still confirms', async () => {
  const h = makeHarness([{ id: 5, desired: 'delete', status: 'disconnected' }]);
  await h.gateway.tick();
  assert.equal(h.sessions.length, 0);
  assert.equal(h.accounts.has(5), false);
});

test('a logged-out account is not restarted until the app resets its status', async () => {
  const h = makeHarness([{ id: 1 }]);
  await h.gateway.tick();
  h.sessions[0].dead = true; // the phone removed the device
  h.accounts.get(1).status = 'logged_out';
  await h.gateway.tick();
  await h.gateway.tick();
  assert.equal(h.sessions.length, 1, 'no restart loop');
  h.accounts.get(1).status = 'starting'; // admin pressed "connect"
  await h.gateway.tick();
  assert.equal(h.sessions.length, 2);
});

test('sessions of accounts that vanished from the app are logged out', async () => {
  const h = makeHarness([{ id: 1 }, { id: 2 }]);
  await h.gateway.tick();
  h.accounts.delete(2);
  await h.gateway.tick();
  assert.equal(h.sessions.find((s) => s.id === 2).loggedOut, 1);
  assert.equal(h.sessions.find((s) => s.id === 1).loggedOut, 0);
});

test('identical status reports are not re-sent, a failed report is retried', async () => {
  let fail = true;
  const sent = [];
  const gateway = new Gateway({
    api: { sync: async () => ({ accounts: [] }), reportState: async (id, p) => { if (fail) throw new Error('down'); sent.push([id, p]); } },
    createSession: () => ({}),
    log: () => {},
  });
  await gateway.report(1, { status: 'connected' });
  fail = false;
  await gateway.report(1, { status: 'connected' }); // retried because the first one failed
  await gateway.report(1, { status: 'connected' }); // duplicate -> skipped
  assert.equal(sent.length, 1);
});

test('outbox items are sent through the right session and the result is reported', async () => {
  const h = makeHarness([{ id: 1 }, { id: 2 }], {
    outbox: [{ id: 10, account_id: 2, to: '972501234567', body: 'hello' }, { id: 11, account_id: 1, to: '14155550100', body: 'boom' }],
  });
  await h.gateway.tick();
  assert.equal(h.sessions.find((s) => s.id === 2).sent.length, 1);
  assert.deepEqual(h.results.find(([id]) => id === 10)[1], { ok: true, wamid: 'W10' });
  const failed = h.results.find(([id]) => id === 11)[1];
  assert.equal(failed.ok, false);
  assert.match(failed.error, /boom/);
});

test('an outbox item for an account that is not connected fails fast instead of waiting', async () => {
  const h = makeHarness([{ id: 1 }]);
  await h.gateway.tick();
  h.sessions[0].connected = false;
  h.queueOutbox([{ id: 20, account_id: 1, to: '972501234567', body: 'x' }, { id: 21, account_id: 99, to: '972501234567', body: 'y' }]);
  await h.gateway.tick();
  assert.deepEqual(h.results.map(([id, r]) => [id, r.ok]), [[20, false], [21, false]]);
});

test('received messages are delivered to the app, and kept and retried while the app is down', async () => {
  const h = makeHarness([{ id: 1 }]);
  await h.gateway.tick();
  const session = h.sessions[0];
  h.setDown(true);
  await session.events.messages([{ wamid: 'A', phone: '972501234567', direction: 'in', body: 'hi' }]);
  assert.equal(h.messages.length, 0);
  assert.equal(h.gateway.pendingReports.length, 1);
  h.setDown(false);
  await h.gateway.tick(); // flushes the pending report first
  assert.equal(h.messages.length, 1);
  assert.equal(h.messages[0][1][0].wamid, 'A');
  assert.equal(h.gateway.pendingReports.length, 0);
});

test('the polling interval suggested by the app is remembered', async () => {
  const h = makeHarness([]);
  await h.gateway.tick();
  assert.equal(h.gateway.nextPollMs, 1000);
});

test('api client sends the bearer token and re-reads it after a 401', async () => {
  const seen = [];
  const tokens = ['old', 'new'];
  const fetchImpl = async (url, opts) => {
    seen.push(opts.headers.Authorization);
    const ok = opts.headers.Authorization === 'Bearer new';
    return { ok, status: ok ? 200 : 401, json: async () => ({ accounts: [{ id: 1 }], outbox: [] }) };
  };
  const api = createApi({ baseUrl: 'http://x', getToken: () => tokens.shift(), fetchImpl });
  assert.deepEqual((await api.sync()).accounts, [{ id: 1 }]);
  assert.deepEqual(seen, ['Bearer old', 'Bearer new']);
});

test('api client throws on server errors', async () => {
  const api = createApi({ baseUrl: 'http://x', getToken: () => 't', fetchImpl: async () => ({ ok: false, status: 500, json: async () => ({}) }) });
  await assert.rejects(api.sync(), /HTTP 500/);
});

test('api requests are aborted when the app does not answer (so the loop cannot hang)', async () => {
  const fetchImpl = (url, opts) => new Promise((resolve, reject) => {
    opts.signal.addEventListener('abort', () => reject(opts.signal.reason));
  });
  const api = createApi({ baseUrl: 'http://x', getToken: () => 't', fetchImpl, timeoutMs: 50 });
  await assert.rejects(api.sync());
});

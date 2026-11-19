// Dev smoke test: does the installed Baileys reach WhatsApp and hand us a QR? (No account is linked.)
import { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import pino from 'pino';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dir = mkdtempSync(join(tmpdir(), 'wa-smoke-'));
const { state } = await useMultiFileAuthState(dir);
let version;
try { ({ version } = await fetchLatestBaileysVersion()); } catch (e) { console.log('version lookup failed', e.message); }
const sock = makeWASocket({ auth: state, version, logger: pino({ level: 'silent' }), printQRInTerminal: false, browser: ['Atlas CRM', 'Chrome', '1.0'] });
const timer = setTimeout(() => { console.log('TIMEOUT: no QR in 40s'); process.exit(2); }, 40000);
sock.ev.on('connection.update', (u) => {
  if (u.qr) { console.log('QR received, length', u.qr.length, 'prefix', u.qr.slice(0, 12)); clearTimeout(timer); sock.end(undefined); process.exit(0); }
  if (u.connection) console.log('connection', u.connection);
});

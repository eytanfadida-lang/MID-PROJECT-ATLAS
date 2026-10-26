// A real WhatsApp linked-device session (Baileys). One per account; the login lives in <authDir>/<account id>.
import { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import pino from 'pino';
import { rm } from 'node:fs/promises';
import { join } from 'node:path';

const RECONNECT_DELAYS_MS = [2000, 5000, 10000, 30000];
const FIRST_QR_TTL_S = 60; // WhatsApp keeps the first QR for 60s, later ones for 20s
const NEXT_QR_TTL_S = 20;
const ERROR_AFTER_FAILURES = 4;

export function createBaileysSessionFactory({ authDir, log = console.log }) {
  let versionPromise;
  const latestVersion = () => {
    versionPromise ||= fetchLatestBaileysVersion().then((r) => r.version).catch(() => undefined);
    return versionPromise;
  };

  return function createSession(account, report) {
    const dir = join(authDir, String(account.id));
    let sock = null;
    let stopping = false;
    let qrCount = 0;
    let failures = 0;
    let timer = null;
    const session = {
      dead: false,

      async start() {
        stopping = false;
        await open();
      },

      // Close the connection but keep the login on disk (the admin can reconnect without scanning again).
      async stop() {
        stopping = true;
        clearTimeout(timer);
        close();
      },

      // Unlink this device from the phone and wipe the login.
      async logout() {
        stopping = true;
        clearTimeout(timer);
        try {
          await sock?.logout();
        } catch (e) {
          log(`#${account.id} logout: ${e.message}`);
        }
        close();
        await rm(dir, { recursive: true, force: true });
      },
    };

    function close() {
      try {
        sock?.end(undefined);
      } catch {
        /* already closed */
      }
      sock = null;
    }

    async function open() {
      const { state, saveCreds } = await useMultiFileAuthState(dir);
      const socket = makeWASocket({
        auth: state,
        version: await latestVersion(),
        logger: pino({ level: 'silent' }),
        browser: ['Atlas CRM', 'Chrome', '1.0'],
        markOnlineOnConnect: false,
        syncFullHistory: false,
      });
      sock = socket;
      socket.ev.on('creds.update', saveCreds);
      socket.ev.on('connection.update', async (update) => {
        if (socket !== sock) return; // an old socket reporting after we replaced it
        if (update.qr) {
          qrCount += 1;
          const qr_image = await QRCode.toDataURL(update.qr, { margin: 1, width: 320 });
          report({ status: 'waiting_qr', qr_image, qr_ttl: qrCount === 1 ? FIRST_QR_TTL_S : NEXT_QR_TTL_S });
        }
        if (update.connection === 'open') {
          failures = 0;
          qrCount = 0;
          const phone = String(socket.user?.id || '').split(':')[0].split('@')[0] || null;
          report({ status: 'connected', phone });
        }
        if (update.connection === 'close') {
          if (stopping) return;
          const code = update.lastDisconnect?.error?.output?.statusCode;
          if (code === DisconnectReason.loggedOut) {
            // The device was removed from the phone: the login is useless now.
            session.dead = true;
            close();
            await rm(dir, { recursive: true, force: true });
            report({ status: 'logged_out' });
            return;
          }
          failures += 1;
          // 515 (restart required) is normal right after scanning the QR - reconnect quickly, no error shown
          const delay = code === DisconnectReason.restartRequired ? 500 : RECONNECT_DELAYS_MS[Math.min(failures - 1, RECONNECT_DELAYS_MS.length - 1)];
          if (failures >= ERROR_AFTER_FAILURES) report({ status: 'error', error: `החיבור נכשל (קוד ${code ?? 'לא ידוע'}), מנסה שוב` });
          else if (code !== DisconnectReason.restartRequired) report({ status: 'starting' });
          log(`#${account.id} closed (code ${code}), retry in ${delay}ms`);
          close();
          timer = setTimeout(() => open().catch((e) => log(`#${account.id} reopen failed: ${e.message}`)), delay);
        }
      });
    }

    return session;
  };
}

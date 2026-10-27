// A real WhatsApp linked-device session (Baileys). One per account; the login lives in <authDir>/<account id>.
import { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason, downloadMediaMessage } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import pino from 'pino';
import { randomBytes } from 'node:crypto';
import { rm } from 'node:fs/promises';
import { join } from 'node:path';
import { MAX_MEDIA_BYTES, buildContent, toReceipts, toRecord } from './messages.js';

const RECONNECT_DELAYS_MS = [2000, 5000, 10000, 30000];
const FIRST_QR_TTL_S = 60; // WhatsApp keeps the first QR for 60s, later ones for 20s
const NEXT_QR_TTL_S = 20;
const ERROR_AFTER_FAILURES = 4;
const TYPING_MS = [500, 1300]; // a short "typing..." before each message, like a person would

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// `api.downloadAttachment(path)` fetches files the admin attached in the app; `sentIds` is shared so echoes of our own
// sends are not reported back as new "phone" messages.
export function createBaileysSessionFactory({ authDir, api, log = console.log }) {
  let versionPromise;
  const latestVersion = () => {
    versionPromise ||= fetchLatestBaileysVersion().then((r) => r.version).catch(() => undefined);
    return versionPromise;
  };

  return function createSession(account, report, events) {
    const dir = join(authDir, String(account.id));
    const logger = pino({ level: 'silent' });
    const sentIds = new Set(); // ids we generated for outgoing messages
    let sock = null;
    let connected = false;
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

      isConnected() {
        return connected && !!sock;
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

      // Send one outbox item (text, or text/caption + attachment). Returns { wamid }.
      async send(item) {
        if (!session.isConnected()) throw new Error('החשבון לא מחובר');
        const jid = `${String(item.to).replace(/\D/g, '')}@s.whatsapp.net`;
        const bytes = item.attachment_url ? await api.downloadAttachment(item.attachment_url) : null;
        const messageId = `3EB0${randomBytes(9).toString('hex').toUpperCase()}`;
        sentIds.add(messageId);
        try {
          await sock.sendPresenceUpdate('composing', jid);
          await sleep(TYPING_MS[0] + Math.random() * (TYPING_MS[1] - TYPING_MS[0]));
          await sock.sendPresenceUpdate('paused', jid);
          const result = await sock.sendMessage(jid, buildContent(item, bytes), { messageId });
          return { wamid: result?.key?.id || messageId };
        } catch (e) {
          sentIds.delete(messageId);
          throw e;
        }
      },
    };

    function close() {
      connected = false;
      try {
        sock?.end(undefined);
      } catch {
        /* already closed */
      }
      sock = null;
    }

    async function handleUpsert(socket, { messages, type }) {
      // "notify" = new/just-delivered messages (including ones that arrived while we were offline). "append" is history.
      if (type !== 'notify') return;
      const records = [];
      for (const message of messages) {
        try {
          if (sentIds.has(message.key?.id)) continue; // echo of something we just sent
          const lookup = async (lid) => socket.signalRepository?.lidMapping?.getPNForLID?.(lid) ?? null;
          const record = await toRecord(message, lookup);
          if (!record) continue;
          if (record.media && record.size <= MAX_MEDIA_BYTES) {
            try {
              const buffer = await downloadMediaMessage(message, 'buffer', {}, { logger, reuploadRequest: socket.updateMediaMessage });
              if (buffer?.length && buffer.length <= MAX_MEDIA_BYTES) {
                record.attachment = { name: record.name, mime: record.mime, data: buffer.toString('base64') };
              }
            } catch (e) {
              log(`#${account.id} media download failed: ${e.message}`);
            }
          }
          delete record.media;
          delete record.size;
          records.push(record);
        } catch (e) {
          log(`#${account.id} could not read a message: ${e.message}`);
        }
      }
      if (records.length) await events.messages(records);
    }

    async function open() {
      const { state, saveCreds } = await useMultiFileAuthState(dir);
      const socket = makeWASocket({
        auth: state,
        version: await latestVersion(),
        logger,
        browser: ['Atlas CRM', 'Chrome', '1.0'],
        markOnlineOnConnect: false,
        syncFullHistory: false,
      });
      sock = socket;
      socket.ev.on('creds.update', saveCreds);
      socket.ev.on('messages.upsert', (payload) => {
        if (socket === sock) handleUpsert(socket, payload).catch((e) => log(`#${account.id} upsert: ${e.message}`));
      });
      socket.ev.on('messages.update', (updates) => {
        if (socket !== sock) return;
        const receipts = toReceipts(updates);
        if (receipts.length) events.receipts(receipts);
      });
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
          connected = true;
          const phone = String(socket.user?.id || '').split(':')[0].split('@')[0] || null;
          report({ status: 'connected', phone });
        }
        if (update.connection === 'close') {
          connected = false;
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

// A real WhatsApp linked-device session (Baileys). One per account; the login lives in <authDir>/<account id>.
import { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason, downloadMediaMessage } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import pino from 'pino';
import { randomBytes } from 'node:crypto';
import { rm } from 'node:fs/promises';
import { join } from 'node:path';
import { MAX_MEDIA_BYTES, buildContent, isRecentIncoming, toReceipts, toRecord, whySkipped } from './messages.js';

const RECONNECT_DELAYS_MS = [2000, 5000, 10000, 30000];
const FIRST_QR_TTL_S = 60; // WhatsApp keeps the first QR for 60s, later ones for 20s
const NEXT_QR_TTL_S = 20;
const ERROR_AFTER_FAILURES = 4;
const TYPING_MS = [500, 1300]; // a short "typing..." before each message, like a person would
const GROUPS_FIRST_REPORT_MS = 8000; // after connecting, report the account's groups (so the admin can pick one per branch)
const GROUPS_REPORT_EVERY_MS = 10 * 60 * 1000;

// "972501234567:12@s.whatsapp.net" / "123456789:3@lid" -> "972501234567" / "123456789"
const idDigits = (id) => String(id || '').split('@')[0].split(':')[0].replace(/\D/g, '');

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
    let groupsTimer = null;

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
        clearInterval(groupsTimer);
        close();
      },

      // Unlink this device from the phone and wipe the login.
      async logout() {
        stopping = true;
        clearTimeout(timer);
        clearInterval(groupsTimer);
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

      // Add one person to a group this account administers. If her privacy settings block being added (403) or she
      // left the group recently (408), she gets the group's invite link in a private message instead.
      async addToGroup(job) {
        if (!session.isConnected()) throw new Error('החשבון לא מחובר');
        const digits = String(job.to).replace(/\D/g, '');
        const [found] = (await sock.onWhatsApp(digits)) || [];
        if (!found?.exists) return { result: 'failed', error: 'המספר לא רשום בוואטסאפ' };
        const [outcome] = (await sock.groupParticipantsUpdate(job.group_jid, [found.jid || `${digits}@s.whatsapp.net`], 'add')) || [];
        const status = String(outcome?.status ?? '');
        log(`#${account.id} group add ${digits} -> ${status || 'no answer'}`);
        if (status === '200') return { result: 'added' };
        if (status === '409') return { result: 'already' };
        if (status === '403' || status === '408') {
          const code = await sock.groupInviteCode(job.group_jid);
          if (!code) return { result: 'failed', error: `ההוספה נחסמה (${status}) ולא התקבל קישור הצטרפות` };
          const body = `${job.invite_text || 'להצטרפות לקבוצת הוואטסאפ של הסטודיו:'}\nhttps://chat.whatsapp.com/${code}`;
          await session.send({ to: digits, body });
          return { result: 'invited' };
        }
        if (status === '401') return { result: 'failed', error: 'הלקוחה חסמה את המספר המקושר' };
        if (status === '404') return { result: 'failed', error: 'המספר לא נמצא בוואטסאפ' };
        if (status === '500') return { result: 'failed', error: 'הקבוצה מלאה' };
        return { result: 'failed', error: `וואטסאפ החזירה קוד ${status || 'לא ידוע'}` };
      },
    };

    // Which groups this account is in, and whether it is an admin there (only admins can add people)
    async function reportGroups(socket) {
      if (socket !== sock || !connected) return;
      try {
        const all = await socket.groupFetchAllParticipating();
        const mine = new Set([idDigits(socket.user?.id), idDigits(socket.user?.lid)].filter(Boolean));
        const groups = Object.values(all || {}).map((g) => {
          const me = (g.participants || []).find((p) => [p.id, p.jid, p.lid, p.phoneNumber].some((x) => mine.has(idDigits(x))));
          return { jid: g.id, subject: g.subject || '', size: (g.participants || []).length, is_admin: !!me?.admin };
        });
        await events.groups(groups);
        log(`#${account.id} reported ${groups.length} group(s)`);
      } catch (e) {
        log(`#${account.id} groups: ${e.message}`);
      }
    }

    function close() {
      connected = false;
      clearInterval(groupsTimer);
      try {
        sock?.end(undefined);
      } catch {
        /* already closed */
      }
      sock = null;
    }

    async function handleUpsert(socket, { messages, type }) {
      // "notify" = new/just-delivered messages (including ones that arrived while we were offline). "append" is history.
      let incoming = messages;
      if (type !== 'notify') {
        // "append" also carries messages that arrived while we were offline: keep the recent ones from customers
        incoming = type === 'append' ? messages.filter((m) => isRecentIncoming(m)) : [];
        log(`#${account.id} upsert type ${type}: ${messages.length} message(s), ${incoming.length} recent`);
        if (!incoming.length) return;
      }
      const records = [];
      for (const message of incoming) {
        try {
          if (sentIds.has(message.key?.id)) continue; // echo of something we just sent
          const lookup = async (lid) => socket.signalRepository?.lidMapping?.getPNForLID?.(lid) ?? null;
          const record = await toRecord(message, lookup);
          if (!record) {
            log(`#${account.id} message skipped: ${await whySkipped(message, lookup)}`);
            continue;
          }
          log(`#${account.id} message ${record.direction} from ${record.phone} (${record.media || 'text'})`);
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
          log(`#${account.id} connected`);
          const phone = String(socket.user?.id || '').split(':')[0].split('@')[0] || null;
          report({ status: 'connected', phone });
          clearInterval(groupsTimer);
          setTimeout(() => reportGroups(socket), GROUPS_FIRST_REPORT_MS);
          groupsTimer = setInterval(() => reportGroups(socket), GROUPS_REPORT_EVERY_MS);
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

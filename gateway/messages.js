// Pure helpers (no WhatsApp connection needed, so they are unit-tested): turn a Baileys message object into the
// small record the Atlas app stores, and map delivery receipts.

const IGNORED_SERVERS = ['@g.us', '@broadcast', '@newsletter', '@status'];
const WRAPPERS = ['ephemeralMessage', 'viewOnceMessage', 'viewOnceMessageV2', 'viewOnceMessageV2Extension', 'documentWithCaptionMessage', 'editedMessage'];
export const MAX_MEDIA_BYTES = 8 * 1024 * 1024;

// Messages can be nested in wrappers (disappearing chats, view-once, ...): peel them off.
export function unwrap(message) {
  let current = message || {};
  for (let i = 0; i < 5; i += 1) {
    const wrapper = WRAPPERS.find((w) => current[w]?.message);
    if (!wrapper) break;
    current = current[wrapper].message;
  }
  return current;
}

const toNumber = (value) => (value && typeof value.toNumber === 'function' ? value.toNumber() : Number(value || 0));
const digitsOf = (jid) => String(jid || '').split('@')[0].split(':')[0].replace(/\D/g, '');

// The phone number behind a chat id. New-style "@lid" ids hide the number: use the alternate id WhatsApp provides, or the
// injected lookup. Returns null for groups, broadcasts, channels, and anything we cannot resolve.
export async function resolvePhone(key, lookupLidToPhone = async () => null) {
  const jid = key?.remoteJid || '';
  if (!jid || IGNORED_SERVERS.some((s) => jid.endsWith(s))) return null;
  if (jid.endsWith('@s.whatsapp.net')) return digitsOf(jid) || null;
  if (jid.endsWith('@lid')) {
    const alt = key.remoteJidAlt || '';
    if (alt.endsWith('@s.whatsapp.net')) return digitsOf(alt) || null;
    const looked = await lookupLidToPhone(jid);
    return looked ? digitsOf(looked) || null : null;
  }
  return null;
}

// What kind of content is it, and the text to show in the chat. media: whether there is a file to download.
export function describe(message) {
  const m = unwrap(message);
  if (m.conversation) return { body: m.conversation };
  if (m.extendedTextMessage?.text) return { body: m.extendedTextMessage.text };
  if (m.imageMessage) return { body: m.imageMessage.caption || '[תמונה]', media: 'image', mime: m.imageMessage.mimetype, size: toNumber(m.imageMessage.fileLength), name: 'image' };
  if (m.videoMessage) return { body: m.videoMessage.caption || '[וידאו]', media: 'video', mime: m.videoMessage.mimetype, size: toNumber(m.videoMessage.fileLength), name: 'video' };
  if (m.documentMessage) {
    const name = m.documentMessage.fileName || 'document';
    return { body: m.documentMessage.caption || `[קובץ: ${name}]`, media: 'document', mime: m.documentMessage.mimetype, size: toNumber(m.documentMessage.fileLength), name };
  }
  if (m.audioMessage) return { body: m.audioMessage.ptt ? '[הודעה קולית]' : '[הקלטה]', media: 'audio', mime: m.audioMessage.mimetype, size: toNumber(m.audioMessage.fileLength), name: 'audio' };
  if (m.stickerMessage) return { body: '[סטיקר]', media: 'sticker', mime: m.stickerMessage.mimetype || 'image/webp', size: toNumber(m.stickerMessage.fileLength), name: 'sticker' };
  if (m.contactMessage) return { body: m.contactMessage.displayName ? `[איש קשר: ${m.contactMessage.displayName}]` : '[איש קשר]' };
  if (m.contactsArrayMessage) return { body: '[אנשי קשר]' };
  if (m.locationMessage || m.liveLocationMessage) return { body: '[מיקום]' };
  if (m.pollCreationMessage || m.pollCreationMessageV3) return { body: '[סקר]' };
  // reactions, deletions/edits (protocol) and key exchanges are not chat messages
  if (m.reactionMessage || m.protocolMessage) return null;
  const meaningful = Object.keys(m).filter((k) => k !== 'messageContextInfo' && k !== 'senderKeyDistributionMessage');
  if (!meaningful.length) return null;
  return { body: '[הודעה לא-טקסטואלית]' };
}

// Baileys message -> record for POST /gateway/accounts/<id>/messages (without the file bytes; the caller adds `attachment`).
export async function toRecord(message, lookupLidToPhone) {
  if (!message?.message || !message.key?.id) return null;
  const phone = await resolvePhone(message.key, lookupLidToPhone);
  if (!phone) return null;
  const info = describe(message.message);
  if (!info) return null;
  return {
    wamid: message.key.id,
    phone,
    direction: message.key.fromMe ? 'out' : 'in',
    body: info.body,
    timestamp: toNumber(message.messageTimestamp) || Math.floor(Date.now() / 1000),
    push_name: message.pushName || null,
    media: info.media || null,
    mime: info.mime || null,
    name: info.name || null,
    size: info.size || 0,
  };
}

// WhatsApp receipt codes -> the statuses the app knows. Anything else (pending, played...) is ignored.
export function mapReceiptStatus(code) {
  if (code === 0) return 'failed';
  if (code === 2) return 'sent';
  if (code === 3) return 'delivered';
  if (code === 4 || code === 5) return 'read';
  return null;
}

// Baileys `messages.update` events -> [{wamid, status}] for messages WE sent.
export function toReceipts(updates) {
  const out = [];
  for (const u of updates || []) {
    if (!u?.key?.fromMe || !u.key.id) continue;
    const status = mapReceiptStatus(u.update?.status);
    if (status) out.push({ wamid: u.key.id, status });
  }
  return out;
}

// What to hand to sock.sendMessage for an outbox item. `bytes` is the downloaded attachment (or null for text).
export function buildContent(item, bytes) {
  if (!item.attachment_url || !bytes) return { text: item.body || '' };
  const mime = (item.attachment_mime || 'application/octet-stream').split(';')[0].trim().toLowerCase();
  const caption = item.body || undefined;
  if (mime.startsWith('image/')) return { image: bytes, caption, mimetype: mime };
  if (mime.startsWith('video/')) return { video: bytes, caption, mimetype: mime };
  if (mime.startsWith('audio/')) return { audio: bytes, mimetype: mime };
  return { document: bytes, caption, mimetype: mime, fileName: item.attachment_name || 'file' };
}

// Why a message was not turned into a record - written to the gateway log so a missing message can be explained.
export async function whySkipped(message, lookupLidToPhone) {
  const jid = message?.key?.remoteJid || '';
  if (!message?.key?.id) return 'no message id';
  if (!jid) return 'no chat id';
  if (IGNORED_SERVERS.some((s) => jid.endsWith(s))) return `ignored chat type (${jid.split('@')[1]})`;
  if (!message.message) return `no content (stub ${message.messageStubType ?? 'none'}; probably could not be decrypted yet)`;
  if (jid.endsWith('@lid') && !(await resolvePhone(message.key, lookupLidToPhone))) return `could not map ${jid} to a phone number (alt: ${message.key.remoteJidAlt || 'none'})`;
  const info = describe(message.message);
  if (!info) return `not a chat message (${Object.keys(unwrap(message.message)).join(',') || 'empty'})`;
  return 'unknown';
}

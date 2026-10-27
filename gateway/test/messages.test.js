// Tests for turning WhatsApp messages into app records (pure functions, no connection): `npm test`
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildContent, describe, mapReceiptStatus, resolvePhone, toReceipts, toRecord, unwrap } from '../messages.js';

const key = (over = {}) => ({ id: 'ABC', remoteJid: '972501234567@s.whatsapp.net', fromMe: false, ...over });

test('plain and extended text', async () => {
  const a = await toRecord({ key: key(), message: { conversation: 'שלום' }, messageTimestamp: 1700000000 });
  assert.deepEqual([a.phone, a.direction, a.body, a.wamid, a.timestamp], ['972501234567', 'in', 'שלום', 'ABC', 1700000000]);
  const b = await toRecord({ key: key({ fromMe: true }), message: { extendedTextMessage: { text: 'תשובה' } } });
  assert.deepEqual([b.direction, b.body], ['out', 'תשובה']);
});

test('timestamps given as Long-like objects are converted', async () => {
  const r = await toRecord({ key: key(), message: { conversation: 'x' }, messageTimestamp: { toNumber: () => 1700000123 } });
  assert.equal(r.timestamp, 1700000123);
});

test('media gets a placeholder or its caption, and is marked for download', async () => {
  const img = await toRecord({ key: key(), message: { imageMessage: { mimetype: 'image/jpeg', fileLength: 1000 } } });
  assert.deepEqual([img.body, img.media, img.mime, img.size], ['[תמונה]', 'image', 'image/jpeg', 1000]);
  const cap = await toRecord({ key: key(), message: { imageMessage: { caption: 'מבצע', mimetype: 'image/png' } } });
  assert.equal(cap.body, 'מבצע');
  const doc = await toRecord({ key: key(), message: { documentMessage: { fileName: 'cv.pdf', mimetype: 'application/pdf' } } });
  assert.deepEqual([doc.body, doc.name], ['[קובץ: cv.pdf]', 'cv.pdf']);
  const voice = await toRecord({ key: key(), message: { audioMessage: { ptt: true, mimetype: 'audio/ogg; codecs=opus' } } });
  assert.equal(voice.body, '[הודעה קולית]');
  assert.equal((await toRecord({ key: key(), message: { stickerMessage: {} } })).body, '[סטיקר]');
});

test('wrapped messages (disappearing / view once) are unwrapped', async () => {
  const wrapped = { ephemeralMessage: { message: { viewOnceMessage: { message: { imageMessage: { caption: 'סוד' } } } } } };
  assert.ok(unwrap(wrapped).imageMessage);
  const r = await toRecord({ key: key(), message: wrapped });
  assert.equal(r.body, 'סוד');
});

test('non chat content is skipped: reactions, protocol messages, empty key exchanges', async () => {
  assert.equal(await toRecord({ key: key(), message: { reactionMessage: { text: '👍' } } }), null);
  assert.equal(await toRecord({ key: key(), message: { protocolMessage: { type: 0 } } }), null);
  assert.equal(await toRecord({ key: key(), message: { senderKeyDistributionMessage: {} } }), null);
  assert.equal(await toRecord({ key: key(), message: null }), null);
  assert.equal((await toRecord({ key: key(), message: { someNewKind: {} } })).body, '[הודעה לא-טקסטואלית]');
});

test('groups, broadcasts, channels and statuses are ignored', async () => {
  for (const jid of ['1203@g.us', 'status@broadcast', '1@newsletter', '1@broadcast']) {
    assert.equal(await toRecord({ key: key({ remoteJid: jid }), message: { conversation: 'x' } }), null, jid);
  }
});

test('@lid chats are resolved through the alternate id or the lookup, otherwise skipped', async () => {
  assert.equal(await resolvePhone({ remoteJid: '99@lid', remoteJidAlt: '972509998877@s.whatsapp.net' }), '972509998877');
  assert.equal(await resolvePhone({ remoteJid: '99@lid' }, async () => '972501112222:5@s.whatsapp.net'), '972501112222');
  assert.equal(await resolvePhone({ remoteJid: '99@lid' }, async () => null), null);
  assert.equal(await resolvePhone({ remoteJid: '972501234567:12@s.whatsapp.net' }), '972501234567');
});

test('delivery receipts map to app statuses and only cover our own messages', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5].map(mapReceiptStatus), ['failed', null, 'sent', 'delivered', 'read', 'read']);
  const out = toReceipts([
    { key: { id: 'M1', fromMe: true }, update: { status: 3 } },
    { key: { id: 'M2', fromMe: false }, update: { status: 4 } },
    { key: { id: 'M3', fromMe: true }, update: { status: 1 } },
    { key: { id: 'M4', fromMe: true }, update: {} },
  ]);
  assert.deepEqual(out, [{ wamid: 'M1', status: 'delivered' }]);
});

test('outgoing content: text, image with caption, audio, and documents', () => {
  assert.deepEqual(buildContent({ body: 'היי' }, null), { text: 'היי' });
  const bytes = Buffer.from('x');
  assert.deepEqual(buildContent({ body: 'ת', attachment_url: '/a.jpg', attachment_mime: 'image/jpeg' }, bytes), { image: bytes, caption: 'ת', mimetype: 'image/jpeg' });
  assert.deepEqual(buildContent({ attachment_url: '/a.ogg', attachment_mime: 'audio/ogg; codecs=opus' }, bytes), { audio: bytes, mimetype: 'audio/ogg' });
  assert.deepEqual(buildContent({ attachment_url: '/a.pdf', attachment_mime: 'application/pdf', attachment_name: 'cv.pdf' }, bytes), {
    document: bytes, caption: undefined, mimetype: 'application/pdf', fileName: 'cv.pdf',
  });
});

test('describe handles contacts and locations', () => {
  assert.equal(describe({ contactMessage: { displayName: 'דנה' } }).body, '[איש קשר: דנה]');
  assert.equal(describe({ locationMessage: {} }).body, '[מיקום]');
});

// A fake session for tests and for trying the UI without a phone (GATEWAY_FAKE=1): it shows a QR that
// refreshes, and "gets scanned" after FAKE_SCAN_AFTER_MS. Once connected it can receive one test message
// (incomingAfterMs > 0) and it acknowledges sends with delivered/read receipts. It never contacts WhatsApp.
import QRCode from 'qrcode';

export function createFakeSessionFactory({
  scanAfterMs = 15000, qrEveryMs = 20000, firstQrTtl = 60, incomingAfterMs = 0, incomingPhone = '972501112233',
  receiptsAfterMs = 300, log = console.log,
} = {}) {
  let counter = 0;
  return function createSession(account, report, events) {
    let timers = [];
    const clear = () => {
      timers.forEach(clearTimeout);
      timers = [];
    };
    let n = 0;
    let connected = false;
    const session = {
      dead: false,
      loggedOut: false,
      sent: [],
      async start() {
        report({ status: 'starting' });
        const showQr = async () => {
          n += 1;
          report({
            status: 'waiting_qr',
            qr_image: await QRCode.toDataURL(`fake-qr-${account.id}-${n}`, { margin: 1, width: 320 }),
            qr_ttl: n === 1 ? firstQrTtl : 20,
          });
          timers.push(setTimeout(showQr, qrEveryMs));
        };
        timers.push(setTimeout(showQr, 200));
        timers.push(setTimeout(() => {
          clear();
          connected = true;
          report({ status: 'connected', phone: `97250${String(1000000 + account.id).slice(-7)}` });
          if (incomingAfterMs > 0) timers.push(setTimeout(() => session.simulateIncoming('שלום, זו הודעת בדיקה'), incomingAfterMs));
        }, scanAfterMs));
      },
      isConnected() {
        return connected;
      },
      async stop() {
        clear();
        connected = false;
      },
      async logout() {
        clear();
        connected = false;
        session.loggedOut = true;
        log(`fake #${account.id} logged out`);
      },
      async send(item) {
        if (!connected) throw new Error('החשבון לא מחובר');
        if (/fail-me/.test(item.body || '')) throw new Error('שליחה נכשלה (מדומה)');
        counter += 1;
        const wamid = `FAKE${String(counter).padStart(6, '0')}`;
        session.sent.push({ ...item, wamid });
        timers.push(setTimeout(() => events.receipts([{ wamid, status: 'delivered' }]), receiptsAfterMs));
        timers.push(setTimeout(() => events.receipts([{ wamid, status: 'read' }]), receiptsAfterMs * 2));
        return { wamid };
      },
      // test helpers
      simulateIncoming(body, phone = incomingPhone, extra = {}) {
        counter += 1;
        return events.messages([{ wamid: `FAKEIN${String(counter).padStart(6, '0')}`, phone, direction: 'in', body, timestamp: Math.floor(Date.now() / 1000), ...extra }]);
      },
      simulateRemovedFromPhone() {
        clear();
        connected = false;
        session.dead = true;
        report({ status: 'logged_out' });
      },
    };
    return session;
  };
}

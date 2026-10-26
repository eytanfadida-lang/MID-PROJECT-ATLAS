// A fake session for tests and for trying the UI without a phone (GATEWAY_FAKE=1): it shows a QR that
// refreshes, and "gets scanned" after FAKE_SCAN_AFTER_MS. It never contacts WhatsApp.
import QRCode from 'qrcode';

export function createFakeSessionFactory({ scanAfterMs = 15000, qrEveryMs = 20000, firstQrTtl = 60, log = console.log } = {}) {
  return function createSession(account, report) {
    let timers = [];
    const clear = () => {
      timers.forEach(clearTimeout);
      timers = [];
    };
    let n = 0;
    const session = {
      dead: false,
      loggedOut: false,
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
          report({ status: 'connected', phone: `97250${String(1000000 + account.id).slice(-7)}` });
        }, scanAfterMs));
      },
      async stop() {
        clear();
      },
      async logout() {
        clear();
        session.loggedOut = true;
        log(`fake #${account.id} logged out`);
      },
      // test helper: simulate the phone removing the linked device
      simulateRemovedFromPhone() {
        clear();
        session.dead = true;
        report({ status: 'logged_out' });
      },
    };
    return session;
  };
}

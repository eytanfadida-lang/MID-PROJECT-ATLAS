/* הפעלה/כיבוי של התראות דחיפה על הודעות חדשות מלקוחות (רק למנהלת - הסקריפט נטען רק למשתמש אדמין).
 * הזרימה: מבקשים הרשאה מהדפדפן -> נרשמים לשירות הדחיפה עם המפתח הציבורי של השרת -> שולחים לשרת את פרטי
 * המנוי (blueprints/push.py). ההתראה עצמה מוצגת ע"י ה-service worker (sw.js). הכפתורים: שורה בגיליון "עוד"
 * (מובייל), פעמון בטופ-בר (שולחן עבודה), ושורת "שליחת התראת בדיקה". */
(function () {
    'use strict';
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta) return;
    var csrf = meta.content;

    var row = document.getElementById('push-row');
    var testRow = document.getElementById('push-test-row');
    var bell = document.getElementById('push-bell');
    if (!row && !bell) return;

    var ua = navigator.userAgent || '';
    var ios = /iphone|ipad|ipod/i.test(ua);
    var standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone;
    var supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    var state = 'loading';
    var busy = false;

    function urlBase64ToUint8Array(b64) {
        var padded = (b64 + '='.repeat((4 - b64.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/');
        var raw = atob(padded);
        var out = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
        return out;
    }

    function sameKey(subscription, keyBytes) {
        var current = subscription.options && subscription.options.applicationServerKey;
        if (!current) return false;
        var a = new Uint8Array(current);
        if (a.length !== keyBytes.length) return false;
        for (var i = 0; i < a.length; i++) if (a[i] !== keyBytes[i]) return false;
        return true;
    }

    function post(url, fields) {
        var body = new URLSearchParams(Object.assign({ csrf_token: csrf }, fields || {}));
        return fetch(url, { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
            .then(function (r) { return r.json().catch(function () { return { ok: false }; }).then(function (j) { j.httpOk = r.ok; return j; }); });
    }

    function sendSubscription(subscription) {
        var json = subscription.toJSON();
        return post('/push/subscribe', { endpoint: json.endpoint, p256dh: json.keys.p256dh, auth: json.keys.auth });
    }

    var LABELS = {
        loading: ['🔔 התראות…', true],
        unsupported: ['🔔 התראות לא נתמכות בדפדפן הזה', true],
        'ios-install': ['🔔 התראות: קודם יש להתקין למסך הבית', true],
        unavailable: ['🔔 התראות: הספרייה עדיין לא מותקנת בשרת', true],
        denied: ['🔕 התראות חסומות - יש לאפשר בהגדרות הדפדפן/הטלפון', true],
        off: ['🔔 הפעלת התראות על הודעות חדשות', false],
        on: ['🔔 התראות פעילות (לחיצה לכיבוי)', false],
        busy: ['🔔 רגע…', true]
    };

    function render(flashText) {
        var label = LABELS[busy ? 'busy' : state];
        var text = flashText || label[0];
        if (row) { row.hidden = false; row.textContent = text; row.disabled = label[1]; }
        if (testRow) testRow.hidden = !(state === 'on' && !busy);
        if (bell) {
            bell.hidden = false;
            bell.innerHTML = state === 'on' ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>' : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.7 3A6 6 0 0 1 18 8c0 3 .6 5.1 1.3 6.6M17 17H3s3-2 3-9c0-.9.2-1.7.5-2.4"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/><path d="M2 2l20 20"/></svg>';
            bell.title = text;
            bell.setAttribute('aria-label', text);
            bell.disabled = label[1];
        }
    }

    function refresh() {
        if (!supported) {
            state = ios && !standalone ? 'ios-install' : 'unsupported';
            return Promise.resolve(render());
        }
        if (Notification.permission === 'denied') {
            state = 'denied';
            return Promise.resolve(render());
        }
        // ה-service worker נרשם אחרי טעינת הדף; אם הוא לא מוכן תוך כמה שניות משהו חסום (למשל הדפדפן מנע אותו)
        var ready = Promise.race([
            navigator.serviceWorker.ready,
            new Promise(function (resolve) { setTimeout(function () { resolve(null); }, 8000); })
        ]);
        return ready.then(function (reg) {
            if (!reg) throw new Error('service worker not ready');
            return reg.pushManager.getSubscription();
        }).then(function (sub) {
            state = sub && Notification.permission === 'granted' ? 'on' : 'off';
            render();
            // סנכרון שקט (פעם בסשן): אם המנוי קיים בדפדפן אבל נמחק בשרת (למשל איפוס מסד) - נרשם מחדש
            if (state === 'on' && !sessionStorage.getItem('push-synced')) {
                sessionStorage.setItem('push-synced', '1');
                sendSubscription(sub).catch(function () {});
            }
        }).catch(function () {
            state = 'unsupported';
            render();
        });
    }

    function enable() {
        busy = true;
        render();
        return Notification.requestPermission().then(function (permission) {
            if (permission !== 'granted') return null;
            return Promise.all([navigator.serviceWorker.ready, fetch('/push/public-key', { credentials: 'same-origin' }).then(function (r) { return r.json(); })])
                .then(function (parts) {
                    var reg = parts[0], info = parts[1];
                    if (!info.available) { state = 'unavailable'; return null; }
                    var key = urlBase64ToUint8Array(info.key);
                    return reg.pushManager.getSubscription().then(function (existing) {
                        // מפתח השרת התחלף (למשל קובץ המפתח נמחק) - המנוי הישן לא תקף יותר
                        if (existing && !sameKey(existing, key)) return existing.unsubscribe().then(function () { return null; });
                        return existing;
                    }).then(function (sub) {
                        return sub || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
                    }).then(function (sub) {
                        return sendSubscription(sub).then(function (res) {
                            if (!res.ok) { return sub.unsubscribe().then(function () { throw new Error(res.error || 'ההרשמה בשרת נכשלה'); }); }
                        });
                    });
                });
        }).catch(function (err) {
            window.alert('לא ניתן להפעיל התראות: ' + (err && err.message ? err.message : err));
        }).then(function () {
            busy = false;
            return refresh();
        });
    }

    function disable() {
        busy = true;
        render();
        return navigator.serviceWorker.ready.then(function (reg) { return reg.pushManager.getSubscription(); }).then(function (sub) {
            if (!sub) return null;
            var endpoint = sub.endpoint;
            return sub.unsubscribe().then(function () { return post('/push/unsubscribe', { endpoint: endpoint }); });
        }).catch(function () {}).then(function () {
            busy = false;
            return refresh();
        });
    }

    function toggle() {
        if (busy) return;
        if (state === 'off') enable(); else if (state === 'on') disable();
    }

    if (row) row.addEventListener('click', toggle);
    if (bell) bell.addEventListener('click', toggle);
    if (testRow) testRow.addEventListener('click', function () {
        testRow.disabled = true;
        post('/push/test').then(function (res) {
            render(res.ok ? '✓ נשלחה התראת בדיקה' : '⚠ ' + (res.error || 'השליחה נכשלה'));
            setTimeout(function () { render(); }, 3500);
        }).catch(function () { render('⚠ השליחה נכשלה'); }).then(function () { testRow.disabled = false; });
    });

    render();   // מציגים מיד (מצב 'טוען') - הכפתור לא נעלם עד שה-service worker מוכן
    refresh();
    // אחרי שהמשתמשת משנה הרשאה בהגדרות הדפדפן וחוזרת לדף - מעדכנים את המצב
    document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') refresh(); });
})();

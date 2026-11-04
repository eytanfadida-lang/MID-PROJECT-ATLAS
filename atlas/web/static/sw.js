/* Service worker של "מנהל תורים".
 *
 * מה הוא עושה:
 *  - מאפשר התקנה כאפליקציה במסך הבית.
 *  - שומר במטמון רק קבצי עיצוב/אייקונים סטטיים (network-first: תמיד הגרסה העדכנית כשיש חיבור).
 *  - כשאין חיבור והמשתמש עובר בין דפים - מציג עמוד "אין חיבור" קצר.
 *  - מציג התראות דחיפה על הודעות חדשות מלקוחות (אירוע push), ופותח את השיחה בלחיצה עליהן.
 *
 * מה הוא בכוונה לא עושה: לא שומר דפי HTML ולא תשובות שרת (שיחות, לידים, לקוחות) - אלה מידע רגיש של
 * לקוחות אמיתיות, ושמירה שלהם במכשיר עלולה לחשוף אותם (למשל במכשיר משותף/אבוד) או להציג מידע ישן.
 * גם בקשות POST (שליחת הודעה, שמירה) עוברות ישירות לשרת, בלי התערבות. */
const CACHE = "manager-static-v1";
const PRECACHE = ["/static/style.css", "/static/offline.html", "/static/icons/icon-192.png"];
const ICON = "/static/icons/icon-192.png";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // ניווט בין דפים: תמיד מהשרת; אם אין חיבור - עמוד "אין חיבור"
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/static/offline.html")));
    return;
  }

  // קבצים סטטיים (/static/...): קודם הרשת (כדי לקבל עדכוני עיצוב), ואם אין חיבור - מהמטמון
  if (url.pathname.startsWith("/static/") && !url.pathname.startsWith("/static/uploads/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) =>
              // קובץ העיצוב מגיע עם ?v=<גרסה> שמשתנה בכל עדכון - מוחקים גרסאות ישנות כדי שהמטמון לא יתנפח
              cache.keys()
                .then((keys) => Promise.all(keys
                  .filter((key) => key.url.includes("/static/style.css") && key.url !== request.url && url.pathname.endsWith("/style.css"))
                  .map((key) => cache.delete(key))))
                .then(() => cache.put(request, copy))
            );
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
  // כל השאר (בדיקות מצב, JSON, קבצים שהועלו) - ללא התערבות
});

/* ---------- התראות דחיפה ---------- */

function parsePush(event) {
  if (!event.data) return {};
  try {
    return event.data.json();
  } catch (e) {
    return { body: event.data.text() };
  }
}

async function updateBadge(unread) {
  // תג מספר על אייקון האפליקציה (היכן שנתמך) = כמה שיחות לא נקראו
  try {
    if (typeof unread !== "number" || !self.navigator || !self.navigator.setAppBadge) return;
    if (unread > 0) await self.navigator.setAppBadge(unread);
    else await self.navigator.clearAppBadge();
  } catch (e) { /* לא קריטי */ }
}

self.addEventListener("push", (event) => {
  const data = parsePush(event);
  event.waitUntil((async () => {
    await updateBadge(data.unread);

    // אם האפליקציה פתוחה ונראית כרגע - הרענון החי כבר מציג את ההודעה, אין טעם להקפיץ גם התראה.
    // (חייבים להציג התראה בכל מקרה אחר: מנוי "userVisibleOnly" שלא מציג התראות עלול להישלל ע"י הדפדפן.)
    // התראת בדיקה (force) מוצגת תמיד, כדי שיהיה אפשר לראות שהיא עובדת
    if (!data.force) {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      if (windows.some((w) => w.visibilityState === "visible" && w.focused)) return;
    }

    await self.registration.showNotification(data.title || "הודעה חדשה", {
      body: data.body || "",
      icon: ICON,
      badge: ICON,
      tag: data.tag || "chat",
      renotify: true,
      dir: "rtl",
      lang: "he",
      vibrate: [120, 60, 120],
      timestamp: Date.now(),
      data: { url: data.url || "/" },
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if ("focus" in client) {
        await client.focus();
        if (client.url !== target && "navigate" in client) {
          try { await client.navigate(target); } catch (e) { /* ננסה לפתוח חלון חדש */ if (self.clients.openWindow) await self.clients.openWindow(target); }
        }
        return;
      }
    }
    if (self.clients.openWindow) await self.clients.openWindow(target);
  })());
});

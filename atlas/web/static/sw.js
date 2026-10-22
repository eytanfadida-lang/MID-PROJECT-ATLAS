/* Service worker של "מנהל תורים".
 *
 * מה הוא עושה:
 *  - מאפשר התקנה כאפליקציה במסך הבית.
 *  - שומר במטמון רק קבצי עיצוב/אייקונים סטטיים (network-first: תמיד הגרסה העדכנית כשיש חיבור).
 *  - כשאין חיבור והמשתמש עובר בין דפים - מציג עמוד "אין חיבור" קצר.
 *
 * מה הוא בכוונה לא עושה: לא שומר דפי HTML ולא תשובות שרת (שיחות, לידים, לקוחות) - אלה מידע רגיש של
 * לקוחות אמיתיות, ושמירה שלהם במכשיר עלולה לחשוף אותם (למשל במכשיר משותף/אבוד) או להציג מידע ישן.
 * גם בקשות POST (שליחת הודעה, שמירה) עוברות ישירות לשרת, בלי התערבות. */
const CACHE = "manager-static-v1";
const PRECACHE = ["/static/style.css", "/static/offline.html", "/static/icons/icon-192.png"];

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

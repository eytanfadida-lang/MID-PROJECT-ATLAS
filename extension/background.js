// Service worker - מחזיק את הטוקן האישי ומבצע את כל קריאות ה-API בפועל (content script בתוך
// web.whatsapp.com לא מבצע fetch ישירות, כדי לא להיתקל ב-CSP של האתר - ראו content.js).
// פרוטוקול ההודעות: content.js/popup.js שולחים {type:"atlasApiRequest", path, options},
// ומקבלים {status, data} בחזרה.

const API_BASE = "https://eytan1985.pythonanywhere.com";

async function apiFetch(path, options = {}) {
  const stored = await chrome.storage.local.get("token");
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (stored.token) headers["Authorization"] = `Bearer ${stored.token}`;

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch (err) {
    return { status: 0, data: { ok: false, error: "לא ניתן להתחבר לשרת" } };
  }

  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    // הטוקן פג תוקף/בוטל - מוחקים אותו כדי שהממשק יבקש התחברות מחדש
    await chrome.storage.local.remove("token");
  }
  return { status: response.status, data };
}

async function handleLogin(username, password) {
  const result = await apiFetch("/api/extension/login", {
    method: "POST",
    body: JSON.stringify({ username, password, label: `Chrome - ${navigator.platform || "מחשב"}` }),
  });
  if (result.status === 200 && result.data.ok) {
    await chrome.storage.local.set({ token: result.data.token, username: result.data.username });
  }
  return result;
}

async function handleLogout() {
  await apiFetch("/api/extension/logout", { method: "POST" });
  await chrome.storage.local.remove(["token", "username"]);
  return { status: 200, data: { ok: true } };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== "object") return false;

  if (message.type === "atlasApiRequest") {
    apiFetch(message.path, message.options || {}).then(sendResponse);
    return true; // תשובה אסינכרונית
  }

  if (message.type === "atlasLogin") {
    handleLogin(message.username, message.password).then(sendResponse);
    return true;
  }

  if (message.type === "atlasLogout") {
    handleLogout().then(sendResponse);
    return true;
  }

  // פתיחת כרטיס הלקוחה ב-Arbox בלשונית חדשה. נעשה כאן ולא ב-content script, כי window.open אחרי
  // המתנה לשרת נחסם ע"י חוסם החלונות הקופצים; chrome.tabs.create לא נחסם
  if (message.type === "atlasOpenArboxProfile") {
    apiFetch(`/api/extension/contacts/${encodeURIComponent(message.phone)}/arbox-profile`).then((result) => {
      const link = result.data && result.data.link;
      if (result.status === 200 && typeof link === "string" && link.startsWith("https://manage.arboxapp.com/")) {
        chrome.tabs.create({ url: link });
      }
      sendResponse(result);
    });
    return true;
  }

  // תמונה של תגובה מהירה, כ-data URL. האתר של וואטסאפ חוסם טעינת תמונות מהשרת שלנו (CSP), ולכן
  // ה-background מוריד אותה ומעביר את התוכן עצמו. רק מתיקיית התמונות של התגובות
  if (message.type === "atlasFetchImage") {
    const path = String(message.path || "");
    if (!path.startsWith("/static/uploads/quick-replies/")) {
      sendResponse({ ok: false });
      return false;
    }
    fetch(`${API_BASE}${path}`)
      .then((response) => {
        if (!response.ok) throw new Error(`status ${response.status}`);
        const type = response.headers.get("Content-Type") || "image/jpeg";
        return response.arrayBuffer().then((buffer) => ({ type, buffer }));
      })
      .then(({ type, buffer }) => {
        const bytes = new Uint8Array(buffer);
        let binary = "";
        for (let i = 0; i < bytes.length; i += 0x8000) {
          binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        }
        sendResponse({ ok: true, dataUrl: `data:${type.split(";")[0]};base64,${btoa(binary)}` });
      })
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (message.type === "atlasAuthState") {
    chrome.storage.local.get(["token", "username"]).then((stored) =>
      sendResponse({ loggedIn: Boolean(stored.token), username: stored.username || null })
    );
    return true;
  }

  return false;
});

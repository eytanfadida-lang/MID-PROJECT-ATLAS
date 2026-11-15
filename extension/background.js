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

  if (message.type === "atlasAuthState") {
    chrome.storage.local.get(["token", "username"]).then((stored) =>
      sendResponse({ loggedIn: Boolean(stored.token), username: stored.username || null })
    );
    return true;
  }

  return false;
});

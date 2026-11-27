// עזרים משותפים לכל ה-content scripts של התוסף (ב-"isolated world"). כל הקבצים שמוגדרים באותה
// רשומת content_scripts ב-manifest רצים באותו הקשר, כך ש-globalThis.AtlasCRM נגיש מכולם.
// סדר הטעינה ב-manifest: shared.js קודם, ואחריו quick-replies.js ו-content.js
(function () {
  function sendToBackground(message) {
    return chrome.runtime.sendMessage(message);
  }

  // כל הקריאות לשרת עוברות דרך ה-background (ראו background.js) ולא fetch ישיר מכאן,
  // כדי לא להיתקל ב-CSP של web.whatsapp.com
  function api(path, { method = "GET", body } = {}) {
    const options = { method };
    if (body !== undefined) options.body = JSON.stringify(body);
    return sendToBackground({ type: "atlasApiRequest", path, options });
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  globalThis.AtlasCRM = {
    LOG: "[AtlasCRM]",
    sendToBackground,
    api,
    escapeHtml,
    // שם פרטי של איש הקשר בשיחה הפתוחה - content.js מעדכן, quick-replies.js משתמש בו ל-{שם}
    contactFirstName: "",
  };
})();

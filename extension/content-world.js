// רץ בהקשר הדף עצמו (world: "MAIN", ראו manifest.json) - רק כך יש גישה למודולים הפנימיים של
// WhatsApp Web. זה החלק השביר ביותר בתוסף: וואטסאפ לא חושפת API רשמי, והמבנה הפנימי עלול
// להשתנות בעדכונים. אם זה מפסיק לעבוד - הסימן יהיה שורות "[AtlasCRM][world]" בקונסול (F12).
//
// WhatsApp Web עברה למערכת המודולים של Meta (Haste/Comet) - לא webpack. מאומת בבדיקה חיה
// (13/11/26): המערך webpackChunkwhatsapp_web_client קיים אבל הוא שריד - ה-runtime לא מגיב
// לדחיפה אליו. המודולים נגישים דרך window.require("שם-מודול"), ואוסף הצ'אטים נמצא
// ב-WAWebCollections.Chat (אותה גישה שספריות קוד פתוח כמו whatsapp-web.js עברו אליה)
(function () {
  const LOG = "[AtlasCRM][world]";
  let failCount = 0;
  let reportedSuccess = false;

  function logThrottled(message, extra) {
    failCount += 1;
    if (failCount <= 3 || failCount % 30 === 0) {
      console.warn(`${LOG} ${message} (attempt ${failCount})`, extra === undefined ? "" : extra);
    }
  }

  function safeRequire(name) {
    if (typeof window.require !== "function") return null;
    try {
      return window.require(name);
    } catch (err) {
      return null;
    }
  }

  function getChatCollection() {
    const collections = safeRequire("WAWebCollections");
    return collections && collections.Chat ? collections.Chat : null;
  }

  function getModels(collection) {
    if (typeof collection.getModelsArray === "function") return collection.getModelsArray();
    return collection.models || collection._models || [];
  }

  function getActiveChatModel(collection) {
    try {
      if (typeof collection.getActive === "function") {
        const active = collection.getActive();
        if (active) return active;
      }
    } catch (err) {
      // ממשיכים לחיפוש לפי דגל
    }
    const models = getModels(collection);
    return models.find((m) => m.active === true) || null;
  }

  function wid(value) {
    if (!value) return null;
    if (typeof value === "string") {
      const [user, server] = value.split("@");
      return { user, server: server || "" };
    }
    return { user: value.user, server: value.server || "" };
  }

  // ייתכן שהצ'אט מזוהה ב-LID (מזהה פרטיות חדש של וואטסאפ, "@lid") ולא במספר טלפון - אז
  // מנסים למצוא את מספר הטלפון האמיתי דרך איש הקשר
  function resolvePhone(model) {
    const chatId = wid(model.id);
    if (!chatId) return { phone: null, server: null };
    if (chatId.server === "c.us" || chatId.server === "s.whatsapp.net") {
      return { phone: chatId.user, server: chatId.server };
    }

    const contact = model.contact || {};
    const candidates = [contact.phoneNumber, contact.id];
    for (const candidate of candidates) {
      const parsed = wid(candidate);
      if (parsed && (parsed.server === "c.us" || parsed.server === "s.whatsapp.net")) {
        return { phone: parsed.user, server: chatId.server };
      }
    }

    const contactApi = safeRequire("WAWebApiContact");
    if (contactApi && typeof contactApi.getPhoneNumber === "function") {
      try {
        const parsed = wid(contactApi.getPhoneNumber(model.id));
        if (parsed && parsed.user) return { phone: parsed.user, server: chatId.server };
      } catch (err) {
        // אין התאמה - נדווח למטה
      }
    }
    return { phone: null, server: chatId.server };
  }

  function getActiveChatInfo() {
    if (typeof window.require !== "function") {
      logThrottled("window.require not available yet");
      return null;
    }
    const collection = getChatCollection();
    if (!collection) {
      logThrottled("WAWebCollections.Chat not found");
      return null;
    }
    const model = getActiveChatModel(collection);
    if (!model) return null; // אין שיחה פתוחה - מצב תקין, לא שגיאה

    const chatId = wid(model.id);
    if (chatId && chatId.server === "g.us") return null; // קבוצה - אין מספר אחד להציג

    const { phone, server } = resolvePhone(model);
    if (!phone) {
      logThrottled("active chat found but phone not resolved", { server });
      return null;
    }

    if (!reportedSuccess) {
      reportedSuccess = true;
      console.info(`${LOG} active chat detected (id server: ${server})`);
    }
    const contact = model.contact || {};
    const name = contact.name || contact.pushname || contact.verifiedName || model.formattedTitle || model.name || null;
    return { phone, name };
  }

  let lastSignature = null;

  // force=true (בקשה מפורשת/רענון) שולחת תמיד, גם אם התוצאה זהה לקודמת - אחרת content.js
  // יכול להישאר תקוע ב"טוען..." כשאין צ'אט פעיל מזוהה
  function pollAndNotify(force) {
    let info = null;
    try {
      info = getActiveChatInfo();
    } catch (err) {
      logThrottled("unexpected error", String(err));
    }
    const signature = info ? `${info.phone}|${info.name}` : "";
    if (force || signature !== lastSignature) {
      lastSignature = signature;
      window.postMessage({ source: "atlas-wa-world", type: "activeChat", info }, "*");
    }
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (event.data?.source !== "atlas-wa-isolated") return;
    if (event.data.type === "requestActiveChat") pollAndNotify(true);
  });

  setInterval(pollAndNotify, 1000);
})();

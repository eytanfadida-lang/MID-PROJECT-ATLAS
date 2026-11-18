// חלון "תגובות מהירות" - כפתור ליד תיבת הכתיבה של וואטסאפ שפותח חלון עם ההודעות השמורות
// (אותה ספרייה כמו בעמוד שיחות הבוט ב-CRM). לחיצה על הודעה מכניסה אותה לתיבת הכתיבה, עם {שם}
// מוחלף בשם הפרטי של איש הקשר (AtlasCRM.contactFirstName, מתעדכן ע"י content.js). עריכת הספרייה
// (הוספה/עריכה/מחיקה/מועדפים/קטגוריות) - רק למנהלת, כמו ב-CRM; השרת אוכף את זה (extension_api.py)
(function () {
  const { api, escapeHtml, LOG } = globalThis.AtlasCRM;

  const host = document.createElement("div");
  host.id = "atlas-qr-host";
  host.style.cssText = "position:fixed; top:0; left:0; z-index:2147483001;";
  document.documentElement.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; font-family: Arial, Helvetica, sans-serif; }
      .qr-btn {
        position: fixed; display: none; width: 34px; height: 34px; border-radius: 50%;
        border: none; background: transparent; cursor: pointer; color: #54656f;
        align-items: center; justify-content: center; padding: 0;
      }
      .qr-btn:hover { background: rgba(0,0,0,0.06); }
      .qr-btn.visible { display: flex; }
      .backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.25); display: none; }
      .backdrop.open { display: block; }
      .modal {
        position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
        width: min(560px, 92vw); max-height: 82vh; background: #fff; border-radius: 16px;
        box-shadow: 0 12px 40px rgba(0,0,0,0.2); direction: rtl; display: flex; flex-direction: column;
        color: #111; font-size: 14px;
      }
      .m-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 20px 10px; gap: 10px; }
      .m-head h3 { margin: 0; font-size: 20px; }
      .head-actions { display: flex; gap: 8px; align-items: center; }
      .btn { border: none; border-radius: 10px; background: #f1f5f9; color: #111; cursor: pointer; font-size: 13px; padding: 8px 14px; }
      .btn.primary { background: #2563eb; color: #fff; }
      .btn.danger { background: #fee2e2; color: #b91c1c; }
      .close { border: none; background: none; font-size: 22px; cursor: pointer; color: #333; padding: 0 4px; }
      .search { margin: 4px 20px 10px; position: relative; }
      .search input { width: 100%; padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 10px; font-size: 14px; }
      .tabs { display: flex; gap: 4px; flex-wrap: wrap; margin: 0 20px 10px; background: #f1f5f9; border-radius: 12px; padding: 4px; }
      .tab { border: none; background: none; border-radius: 9px; padding: 7px 12px; cursor: pointer; font-size: 13px; color: #333; }
      .tab.active { background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.1); font-weight: bold; }
      .list { overflow-y: auto; padding: 4px 20px 20px; display: flex; flex-direction: column; gap: 10px; }
      .card { border: 1px solid #e5e7eb; border-radius: 14px; padding: 14px 16px; cursor: pointer; position: relative; }
      .card:hover { border-color: #93c5fd; background: #f8fbff; }
      .card-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }
      .card-title { font-weight: bold; font-size: 15px; }
      .card-tools { display: flex; gap: 2px; align-items: center; }
      .star, .edit { border: none; background: none; cursor: pointer; font-size: 18px; padding: 0 2px; color: #cbd5e1; }
      .star.on { color: #eab308; }
      .star:disabled { cursor: default; }
      .edit { font-size: 14px; color: #94a3b8; }
      .card-body {
        color: #374151; font-size: 13px; line-height: 1.6; white-space: pre-wrap;
        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
      }
      .empty { color: #999; text-align: center; padding: 30px 0; }
      .card-image { display: block; max-width: 100%; max-height: 120px; border-radius: 8px; margin-top: 6px; object-fit: cover; }
      .image-current { display: flex; align-items: center; gap: 10px; }
      .image-current img { max-width: 120px; max-height: 80px; border-radius: 8px; object-fit: cover; }
      .link { border: none; background: none; color: #b91c1c; cursor: pointer; font-size: 12px; text-decoration: underline; padding: 0; }
      .form { padding: 4px 20px 20px; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
      .form label { font-size: 12px; color: #666; }
      .form input, .form textarea { width: 100%; padding: 8px 10px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; font-family: inherit; }
      .form textarea { min-height: 140px; resize: vertical; }
      .form-actions { display: flex; gap: 8px; justify-content: space-between; }
      .hint { font-size: 12px; color: #888; }
      .error { background: #fee2e2; color: #b91c1c; padding: 6px 10px; border-radius: 8px; font-size: 13px; margin: 0 20px 8px; }
    </style>
    <button class="qr-btn" title="תגובות מהירות">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 5h16v11H8l-4 4z"/><path d="M13 8l-2 3h3l-2 3"/>
      </svg>
    </button>
    <div class="backdrop">
      <div class="modal" role="dialog" aria-label="תגובות מהירות"></div>
    </div>
  `;

  const qrBtn = shadow.querySelector(".qr-btn");
  const backdrop = shadow.querySelector(".backdrop");
  const modal = shadow.querySelector(".modal");

  let library = { replies: [], categories: [], can_edit: false };
  let tab = "all"; // "all" | "fav" | שם קטגוריה
  let query = "";
  let editing = null; // null = רשימה; {} = תגובה חדשה; אובייקט = עריכה
  let errorMessage = "";

  // --- תמונות של תגובות (מגיעות מה-background כ-data URL, ראו background.js) ---

  const imageCache = new Map();
  function loadImage(path) {
    if (!imageCache.has(path)) {
      imageCache.set(path, globalThis.AtlasCRM.sendToBackground({ type: "atlasFetchImage", path }).then((result) => {
        if (!result || !result.ok) {
          imageCache.delete(path);
          throw new Error("image load failed");
        }
        return result.dataUrl;
      }));
    }
    return imageCache.get(path);
  }

  // ממלאת את התמונות הממוזערות שברשימה אחרי שהיא נבנתה (הטעינה אסינכרונית)
  function fillImages(root) {
    root.querySelectorAll("img[data-image-path]").forEach((img) => {
      loadImage(img.dataset.imagePath).then((url) => { img.src = url; }).catch(() => img.remove());
    });
  }

  function dataUrlToFile(dataUrl, name) {
    const [head, b64] = dataUrl.split(",");
    const type = (head.match(/data:([^;]+)/) || [])[1] || "image/jpeg";
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new File([bytes], name, { type });
  }

  // --- תיבת הכתיבה של וואטסאפ ---

  // תיבת הכתיבה היא contenteditable; גם שדה החיפוש ברשימת השיחות עשוי להיות כזה, לכן לוקחים את
  // הנמוכה ביותר על המסך (תיבת ההודעה תמיד בתחתית השיחה)
  function findComposer() {
    const boxes = Array.from(document.querySelectorAll('div[contenteditable="true"]')).filter((el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    boxes.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    const lowest = boxes[0];
    if (!lowest || lowest.getBoundingClientRect().top < window.innerHeight * 0.5) return null;
    return lowest;
  }

  // מיקום הכפתור: בתוך הקצה השמאלי של תיבת הכתיבה (בעברית הטקסט מתחיל מימין, אז השמאל פנוי),
  // ומוסיפים לתיבה ריפוד כדי שטקסט ארוך לא יעבור מתחת לכפתור
  function positionButton() {
    const composer = findComposer();
    if (!composer) {
      qrBtn.classList.remove("visible");
      return;
    }
    const rect = composer.getBoundingClientRect();
    if (composer.style.paddingLeft !== "38px") composer.style.paddingLeft = "38px";
    qrBtn.style.left = `${Math.round(rect.left + 2)}px`;
    qrBtn.style.top = `${Math.round(rect.top + rect.height / 2 - 17)}px`;
    qrBtn.classList.add("visible");
  }
  setInterval(positionButton, 500);
  window.addEventListener("resize", positionButton);

  // מכניסה טקסט לתיבת הכתיבה. וואטסאפ משתמשת בעורך (Lexical) שמגיב לאירועי הדבקה - זו הדרך
  // שמשמרת גם ירידות שורה. אם ההדבקה לא נקלטה, נופלים ל-insertText
  function insertIntoComposer(textToInsert) {
    const composer = findComposer();
    if (!composer) return false;
    composer.focus();
    const before = composer.innerText;
    const clipboard = new DataTransfer();
    clipboard.setData("text/plain", textToInsert);
    composer.dispatchEvent(new ClipboardEvent("paste", { clipboardData: clipboard, bubbles: true, cancelable: true }));
    setTimeout(() => {
      if (composer.innerText === before) {
        console.info(`${LOG} paste not accepted, falling back to insertText`);
        document.execCommand("insertText", false, textToInsert);
      }
    }, 80);
    return true;
  }

  // שליחה עם תמונה: מדביקים את התמונה בתיבת הכתיבה - וואטסאפ פותחת את חלון התצוגה המקדימה שלה, עם שדה
  // כיתוב. אחרי שהחלון נפתח, מכניסים את הטקסט לשדה הכיתוב (שמקבל את הפוקוס). השליחה עצמה - בלחיצה שלך
  async function insertImageWithCaption(imagePath, caption) {
    const composer = findComposer();
    if (!composer) return false;
    const dataUrl = await loadImage(imagePath);
    const file = dataUrlToFile(dataUrl, imagePath.split("/").pop() || "image.jpg");
    composer.focus();
    const clipboard = new DataTransfer();
    clipboard.items.add(file);
    composer.dispatchEvent(new ClipboardEvent("paste", { clipboardData: clipboard, bubbles: true, cancelable: true }));
    if (!caption) return true;
    // מחכים שחלון התמונה ייפתח ושדה הכיתוב יקבל פוקוס (עד כ-3 שניות)
    for (let i = 0; i < 15; i++) {
      await new Promise((resolve) => setTimeout(resolve, 200));
      const active = document.activeElement;
      if (active && active !== composer && active.isContentEditable) {
        const text = new DataTransfer();
        text.setData("text/plain", caption);
        const before = active.innerText;
        active.dispatchEvent(new ClipboardEvent("paste", { clipboardData: text, bubbles: true, cancelable: true }));
        setTimeout(() => {
          if (active.innerText === before) document.execCommand("insertText", false, caption);
        }, 80);
        return true;
      }
    }
    // החלון לא נפתח - לפחות הטקסט ייכנס לתיבת הכתיבה הרגילה
    console.info(`${LOG} image preview did not open, inserting text only`);
    insertIntoComposer(caption);
    alert("לא הצלחתי לצרף את התמונה אוטומטית - הטקסט הוכנס. אפשר לצרף את התמונה ידנית");
    return true;
  }

  // --- נתונים ---

  async function loadLibrary() {
    const result = await api("/api/extension/quick-replies");
    if (result.status === 200 && result.data.ok) {
      library = result.data;
      errorMessage = "";
    } else {
      errorMessage = result.status === 401 ? "צריך להתחבר לתוסף (סמל התוסף למעלה)" : "לא הצלחתי לטעון את התגובות";
    }
  }

  async function mutate(path, body) {
    const result = await api(path, { method: "POST", body: body || {} });
    if (result.status === 200 && result.data.ok) {
      library = result.data;
      errorMessage = "";
      return true;
    }
    errorMessage = result.data?.error || `שגיאה (${result.status})`;
    return false;
  }

  // --- רינדור ---

  function visibleReplies() {
    const q = query.trim().toLowerCase();
    return library.replies.filter((reply) => {
      if (tab === "fav" && !reply.favorite) return false;
      if (tab !== "all" && tab !== "fav" && reply.category !== tab) return false;
      if (q && !`${reply.title} ${reply.body}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderList() {
    const tabs = [["all", "הכל"], ["fav", "מועדפים"]].concat(library.categories.map((c) => [c, c]));
    const tabsHtml = tabs
      .map(([key, label]) => `<button class="tab${tab === key ? " active" : ""}" data-tab="${escapeHtml(key)}">${escapeHtml(label)}</button>`)
      .join("") + (library.can_edit ? `<button class="tab" data-action="add-category">+ קטגוריה</button>` : "");

    modal.innerHTML = `
      <div class="m-head">
        <h3>תגובות מהירות</h3>
        <div class="head-actions">
          ${library.can_edit ? `<button class="btn" data-action="new">הוסף תגובה חדשה +</button>` : ""}
          <button class="close" data-action="close" title="סגירה">×</button>
        </div>
      </div>
      ${errorMessage ? `<div class="error">${escapeHtml(errorMessage)}</div>` : ""}
      <div class="search"><input type="search" placeholder="חיפוש תגובות..." value="${escapeHtml(query)}" /></div>
      <div class="tabs">${tabsHtml}</div>
      <div class="list">${cardsHtml()}</div>
    `;
    fillImages(modal);
    const searchInput = modal.querySelector(".search input");
    searchInput.addEventListener("input", () => {
      query = searchInput.value;
      // מרנדרים רק את הרשימה, כדי לא לאבד את הפוקוס בשדה החיפוש תוך כדי הקלדה
      modal.querySelector(".list").innerHTML = cardsHtml();
      fillImages(modal);
    });
    searchInput.focus();
  }

  function cardsHtml() {
    const html = visibleReplies().map((reply) => `
      <div class="card" data-action="use" data-id="${reply.id}">
        <div class="card-head">
          <span class="card-title">${escapeHtml(reply.title)}</span>
          <span class="card-tools">
            ${library.can_edit ? `<button class="edit" data-action="edit" data-id="${reply.id}" title="עריכה">✎</button>` : ""}
            <button class="star${reply.favorite ? " on" : ""}" data-action="star" data-id="${reply.id}"
              title="מועדף"${library.can_edit ? "" : " disabled"}>★</button>
          </span>
        </div>
        ${reply.image_url ? `<img class="card-image" alt="" data-image-path="${escapeHtml(reply.image_url)}">` : ""}
        ${reply.body ? `<div class="card-body">${escapeHtml(reply.body)}</div>` : ""}
      </div>`).join("");
    return html || `<div class="empty">אין תגובות כאן</div>`;
  }

  function renderForm() {
    const reply = editing;
    const isNew = !reply.id;
    const categoryOptions = library.categories.map((c) => `<option value="${escapeHtml(c)}">`).join("");
    modal.innerHTML = `
      <div class="m-head">
        <h3>${isNew ? "תגובה חדשה" : "עריכת תגובה"}</h3>
        <button class="close" data-action="back" title="חזרה">×</button>
      </div>
      ${errorMessage ? `<div class="error">${escapeHtml(errorMessage)}</div>` : ""}
      <form class="form">
        <label>כותרת<input name="title" maxlength="80" value="${escapeHtml(reply.title || "")}" /></label>
        <label>טקסט ההודעה<textarea name="body" maxlength="4000">${escapeHtml(reply.body || "")}</textarea></label>
        <span class="hint">אפשר לכתוב {שם} - יוחלף בשם הפרטי של הלקוחה כשמכניסים את ההודעה</span>
        <label>קטגוריה<input name="category" list="atlas-qr-cats" maxlength="80" value="${escapeHtml(reply.category || (tab !== "all" && tab !== "fav" ? tab : ""))}" /></label>
        <datalist id="atlas-qr-cats">${categoryOptions}</datalist>
        <label>תמונה (אופציונלי) - תישלח עם הטקסט ככיתוב
          ${reply.image_url ? `<span class="image-current"><img alt="" data-image-path="${escapeHtml(reply.image_url)}"><button class="link" type="button" data-action="remove-image">הסרת התמונה</button></span>` : ""}
          <input type="file" name="image" accept="image/jpeg,image/png,image/webp,image/gif" />
        </label>
        <label><input type="checkbox" name="favorite" style="width:auto"${reply.favorite ? " checked" : ""} /> מועדף</label>
        <div class="form-actions">
          <div style="display:flex; gap:8px">
            <button class="btn primary" type="submit">שמירה</button>
            <button class="btn" type="button" data-action="back">ביטול</button>
          </div>
          ${isNew ? "" : `<button class="btn danger" type="button" data-action="delete" data-id="${reply.id}">מחיקה</button>`}
        </div>
      </form>
    `;
    fillImages(modal);
    modal.querySelector('textarea[name="body"]').focus();
  }

  function render() {
    if (editing) renderForm();
    else renderList();
  }

  async function openModal() {
    editing = null;
    query = "";
    backdrop.classList.add("open");
    modal.innerHTML = `<div class="empty">טוען...</div>`;
    await loadLibrary();
    render();
  }

  function closeModal() {
    backdrop.classList.remove("open");
    editing = null;
  }

  // --- אירועים ---

  qrBtn.addEventListener("click", openModal);

  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });

  // Escape סוגר את החלון שלנו - ועוצרים אותו שלא יגיע גם לוואטסאפ (שם הוא סוגר את השיחה)
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && backdrop.classList.contains("open")) {
      event.stopImmediatePropagation();
      event.preventDefault();
      closeModal();
    }
  }, true);

  // הקלדה בשדות שלנו לא תגיע לוואטסאפ - אחרת היא "חוטפת" את ההקלדה לתיבת ההודעה שלה
  ["keydown", "keyup", "keypress", "paste"].forEach((type) => {
    host.addEventListener(type, (event) => event.stopPropagation());
  });

  modal.addEventListener("click", async (event) => {
    const tabBtn = event.target.closest("[data-tab]");
    if (tabBtn) {
      tab = tabBtn.dataset.tab;
      render();
      return;
    }
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    const reply = library.replies.find((r) => String(r.id) === target.dataset.id);

    if (action === "close") {
      closeModal();
    } else if (action === "use" && reply) {
      const firstName = globalThis.AtlasCRM.contactFirstName || "";
      const textToInsert = reply.body.replace(/\{שם\}/g, firstName).replace(/ {2,}/g, " ");
      closeModal();
      if (reply.image_url) {
        const done = await insertImageWithCaption(reply.image_url, textToInsert).catch(() => false);
        if (!done) alert("לא מצאתי את תיבת הכתיבה או את התמונה - נסי לפתוח את השיחה ולנסות שוב");
        return;
      }
      if (!insertIntoComposer(textToInsert)) {
        await navigator.clipboard.writeText(textToInsert).catch(() => {});
        alert("לא מצאתי את תיבת הכתיבה - ההודעה הועתקה, אפשר להדביק (Ctrl+V)");
      }
    } else if (action === "star" && reply && library.can_edit) {
      event.stopPropagation();
      await mutate(`/api/extension/quick-replies/${reply.id}/favorite`, { favorite: !reply.favorite });
      render();
    } else if (action === "edit" && reply) {
      event.stopPropagation();
      editing = { ...reply };
      errorMessage = "";
      render();
    } else if (action === "new") {
      editing = {};
      errorMessage = "";
      render();
    } else if (action === "back") {
      editing = null;
      errorMessage = "";
      render();
    } else if (action === "delete") {
      if (!confirm("למחוק את התגובה הזו? היא תימחק לכל העובדות.")) return;
      if (await mutate(`/api/extension/quick-replies/${target.dataset.id}/delete`)) editing = null;
      render();
    } else if (action === "remove-image") {
      editing.remove_image = true;
      target.closest(".image-current").remove();
    } else if (action === "add-category") {
      const name = (prompt("שם הקטגוריה החדשה:") || "").trim();
      if (!name) return;
      if (await mutate("/api/extension/quick-replies/categories", { name })) tab = name;
      render();
    }
  });

  modal.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const fields = Object.fromEntries(new FormData(form).entries());
    const file = form.querySelector('input[name="image"]').files[0];
    let imageData = null;
    if (file) {
      if (file.size > 5 * 1024 * 1024) {
        errorMessage = "התמונה גדולה מדי (עד 5MB)";
        render();
        return;
      }
      imageData = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
    }
    const ok = await mutate("/api/extension/quick-replies/save", {
      id: editing.id || null,
      title: fields.title,
      body: fields.body,
      category: fields.category,
      favorite: Boolean(fields.favorite),
      image_data: imageData,
      remove_image: Boolean(editing.remove_image),
    });
    if (ok) editing = null;
    render();
  });
})();

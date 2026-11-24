// פאנל "מידע לקוח" בצד של WhatsApp Web. רץ ב-"isolated world" הרגיל - יש לו גישה מלאה ל-DOM
// של הדף, אבל לא למשתני ה-JS הפנימיים של וואטסאפ; לכן content-world.js (world: "MAIN") מזהה את
// השיחה הפתוחה ומדווח לכאן דרך window.postMessage. עזרים משותפים: shared.js (globalThis.AtlasCRM)
(function () {
  const { LOG, api, sendToBackground, escapeHtml } = globalThis.AtlasCRM;
  const CRM_BASE = globalThis.ATLAS_BASE_URL;

  // --- בניית הפאנל (Shadow DOM - מבודד מה-CSS של וואטסאפ בשני הכיוונים) ---

  const host = document.createElement("div");
  host.id = "atlas-crm-host";
  host.style.cssText = "position:fixed; top:0; left:0; z-index:2147483000;";
  document.documentElement.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; font-family: Arial, Helvetica, sans-serif; }
      .panel {
        position: fixed; top: 0; left: 0; height: 100vh;
        width: var(--panel-w, 340px);
        background: #fff; border-right: 1px solid #ddd;
        direction: rtl; display: flex; flex-direction: column;
        transform: translateX(calc(-1 * var(--panel-w, 340px)));
        transition: transform 0.2s ease;
        font-size: 13px; color: #111;
      }
      .panel.open { transform: translateX(0); }
      .panel.resizing, .toggle.resizing { transition: none; }
      .resize-handle {
        position: absolute; top: 0; right: -4px; width: 8px; height: 100%;
        cursor: ew-resize; z-index: 2;
      }
      .resize-handle:hover, .panel.resizing .resize-handle { background: rgba(37, 99, 235, 0.25); }
      .toggle {
        position: fixed; top: 70px; left: 0;
        background: #2563eb; color: #fff; border: none; border-radius: 0 6px 6px 0;
        padding: 10px 6px; cursor: pointer; writing-mode: vertical-rl; font-size: 12px;
        transition: left 0.2s ease;
      }
      .toggle.open { left: var(--panel-w, 340px); }
      .header {
        padding: 12px 14px; border-bottom: 1px solid #eee;
        display: flex; align-items: center; justify-content: space-between; gap: 8px;
      }
      .header h2 { font-size: 14px; margin: 0; white-space: nowrap; }
      .header-actions { display: flex; align-items: center; gap: 4px; }
      .icon-btn {
        border: none; background: none; cursor: pointer; font-size: 14px; color: #2563eb;
        padding: 2px 6px; border-radius: 4px;
      }
      .icon-btn.small { font-size: 12px; font-weight: bold; }
      .icon-btn:hover { background: #eef2ff; }
      .body { padding: 14px; overflow-y: auto; overflow-x: hidden; flex: 1; zoom: var(--text-scale, 1); }

      .error { background: #fee2e2; color: #b91c1c; padding: 6px 8px; border-radius: 6px; margin-bottom: 10px; font-size: 12px; }
      .muted { color: #999; font-size: 12px; }
      .name { font-size: 16px; font-weight: bold; margin-bottom: 2px; }
      .source { color: #999; font-size: 11px; margin-bottom: 10px; }
      .kv {
        display: flex; justify-content: space-between; align-items: center; gap: 12px;
        padding: 6px 0; border-bottom: 1px solid #f3f3f3; min-height: 32px;
      }
      .kv-label { color: #888; font-size: 12px; flex-shrink: 0; }
      .kv-value { font-size: 13px; text-align: left; word-break: break-word; display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; align-items: center; }
      .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; color: #fff; font-size: 12px; }
      .debt { color: #dc2626; font-weight: bold; }

      select, input, textarea {
        font-family: inherit; font-size: 12px; border: 1px solid #ccc; border-radius: 6px;
        padding: 5px 7px; background: #fff; color: #111;
      }
      textarea { width: 100%; resize: vertical; min-height: 54px; }
      .status-select { border-width: 2px; font-weight: bold; }
      .btn {
        border: none; border-radius: 6px; background: #2563eb; color: #fff; cursor: pointer;
        font-size: 12px; padding: 5px 10px;
      }
      .btn.ghost { background: #f1f5f9; color: #111; border: 1px solid #e2e8f0; }
      .btn:disabled { opacity: 0.5; cursor: default; }
      .pill-btn {
        border: 1px solid #e2e8f0; background: #f8fafc; color: #111; border-radius: 14px;
        font-size: 12px; padding: 3px 10px; cursor: pointer;
      }
      .pill-btn:hover { background: #eef2ff; }
      .tag {
        display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 12px;
        font-size: 12px; color: #fff;
      }
      .tag button { border: none; background: none; color: #fff; cursor: pointer; padding: 0; font-size: 12px; opacity: 0.8; }
      .inline-form { display: flex; gap: 6px; margin-top: 6px; width: 100%; }
      .inline-form input { flex: 1; min-width: 0; }
      .stack-form { display: flex; flex-direction: column; gap: 6px; margin: 6px 0 10px; }
      .name-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
      .pills { display: flex; gap: 6px; flex-shrink: 0; }
      .pill-link {
        display: inline-flex; align-items: center; gap: 3px; height: 0.5cm; padding: 0 7px;
        border: 1px solid #d1d5db; background: #fff; color: #1f2937; border-radius: 999px;
        font-size: 11px; font-weight: 600; cursor: pointer; text-decoration: none; font-family: inherit;
        direction: ltr; white-space: nowrap;
      }
      .pill-link:hover { background: #f3f4f6; }
      .pill-link:disabled { opacity: 0.6; cursor: default; }
      .pill-link svg { width: 10px; height: 10px; }

      .section { border-top: 1px solid #eee; margin-top: 8px; }
      .section-head {
        display: flex; justify-content: space-between; align-items: center; width: 100%;
        background: none; border: none; cursor: pointer; padding: 10px 0; font-size: 13px; font-weight: bold; color: #222;
      }
      .section-head .chev { color: #999; font-weight: normal; transition: transform 0.15s; }
      .section.open .chev { transform: rotate(180deg); }
      .section-body { display: none; padding-bottom: 8px; }
      .section.open .section-body { display: block; }
      .notes-box {
        white-space: pre-wrap; background: #f9f9f9; border-radius: 6px; padding: 8px;
        max-height: 180px; overflow-y: auto; font-size: 12px; margin-bottom: 6px;
      }
      .task { display: flex; align-items: flex-start; gap: 6px; padding: 5px 0; border-bottom: 1px solid #f3f3f3; }
      .task.done .task-title { text-decoration: line-through; color: #999; }
      .task-title { flex: 1; font-size: 12px; }
      .task-due { font-size: 11px; color: #666; white-space: nowrap; }
      .task-due.overdue { color: #dc2626; font-weight: bold; }
      .x-btn { border: none; background: none; color: #bbb; cursor: pointer; font-size: 14px; padding: 0 2px; }
      .x-btn:hover { color: #dc2626; }
      .visit-row { display: flex; justify-content: space-between; gap: 6px; padding: 5px 0; border-bottom: 1px solid #f0f0f0; font-size: 12px; }
      .activity { padding: 5px 0; border-bottom: 1px solid #f3f3f3; font-size: 12px; }
      .activity .meta { color: #999; font-size: 11px; }
      .manual-phone { display: flex; gap: 6px; margin-top: 8px; }
      .manual-phone input { flex: 1; }
    </style>
    <button class="toggle">CRM</button>
    <div class="panel">
      <div class="resize-handle" title="גררי כדי לשנות רוחב"></div>
      <div class="header">
        <h2>מידע לקוח</h2>
        <div class="header-actions">
          <button class="icon-btn small" data-zoom="-1" title="הקטנת טקסט">A−</button>
          <button class="icon-btn small" data-zoom="1" title="הגדלת טקסט">A+</button>
          <button class="icon-btn refresh-btn" title="רענון">⟳</button>
        </div>
      </div>
      <div class="body"></div>
    </div>
  `;

  // הקלדה בשדות הפאנל לא תגיע לוואטסאפ - אחרת היא "חוטפת" את ההקלדה לתיבת ההודעה שלה
  ["keydown", "keyup", "keypress", "paste"].forEach((type) => {
    host.addEventListener(type, (event) => event.stopPropagation());
  });

  const panelEl = shadow.querySelector(".panel");
  const toggleEl = shadow.querySelector(".toggle");
  const bodyEl = shadow.querySelector(".body");
  const refreshBtn = shadow.querySelector(".refresh-btn");

  // --- פריסה: הפאנל "דוחף" את וואטסאפ הצידה במקום לצוף מעליה ולהסתיר חלק מהשיחה. ---
  // מצמצמים את ה-body של וואטסאפ ברוחב הפאנל; transform על ה-body הופך אותו לבסיס של
  // אלמנטים ב-position:fixed (תפריטים/חלונות קופצים של וואטסאפ), כך שגם הם זזים יחד איתו.
  // ה-host שלנו יושב על documentElement ולא בתוך ה-body, אז הוא לא מושפע מזה
  const MIN_WIDTH = 260;
  const DEFAULT_WIDTH = 340;
  const SCALE_STEPS = [0.85, 0.9, 1, 1.1, 1.2, 1.3, 1.4];

  let panelOpen = true;
  let panelWidth = DEFAULT_WIDTH;
  let scaleIndex = SCALE_STEPS.indexOf(1);

  const layoutStyle = document.createElement("style");
  layoutStyle.id = "atlas-crm-layout";
  (document.head || document.documentElement).appendChild(layoutStyle);

  function maxWidth() {
    return Math.max(MIN_WIDTH, Math.min(700, Math.floor(window.innerWidth * 0.6)));
  }

  function clampWidth(width) {
    return Math.min(maxWidth(), Math.max(MIN_WIDTH, Math.round(width)));
  }

  function applyLayout() {
    host.style.setProperty("--panel-w", `${panelWidth}px`);
    host.style.setProperty("--text-scale", String(SCALE_STEPS[scaleIndex]));
    panelEl.classList.toggle("open", panelOpen);
    toggleEl.classList.toggle("open", panelOpen);
    layoutStyle.textContent = panelOpen
      ? `body { margin-left: ${panelWidth}px !important; width: calc(100% - ${panelWidth}px) !important; ` +
        `transform: translateZ(0); overflow: hidden !important; }`
      : "";
  }

  function savePrefs() {
    chrome.storage.local.set({ atlasPanelOpen: panelOpen, atlasPanelWidth: panelWidth, atlasTextScale: scaleIndex });
  }

  toggleEl.addEventListener("click", () => {
    panelOpen = !panelOpen;
    applyLayout();
    savePrefs();
  });

  shadow.querySelectorAll("[data-zoom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      scaleIndex = Math.min(SCALE_STEPS.length - 1, Math.max(0, scaleIndex + Number(btn.dataset.zoom)));
      applyLayout();
      savePrefs();
    });
  });

  const handleEl = shadow.querySelector(".resize-handle");
  handleEl.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handleEl.setPointerCapture(event.pointerId);
    panelEl.classList.add("resizing");
    toggleEl.classList.add("resizing");
  });
  handleEl.addEventListener("pointermove", (event) => {
    if (!handleEl.hasPointerCapture(event.pointerId)) return;
    panelWidth = clampWidth(event.clientX); // הפאנל מוצמד לשמאל, אז הרוחב = מיקום העכבר
    applyLayout();
  });
  handleEl.addEventListener("pointerup", (event) => {
    handleEl.releasePointerCapture(event.pointerId);
    panelEl.classList.remove("resizing");
    toggleEl.classList.remove("resizing");
    savePrefs();
  });

  window.addEventListener("resize", () => {
    panelWidth = clampWidth(panelWidth);
    applyLayout();
  });

  applyLayout();
  chrome.storage.local.get(["atlasPanelOpen", "atlasPanelWidth", "atlasTextScale"]).then((prefs) => {
    if (typeof prefs.atlasPanelOpen === "boolean") panelOpen = prefs.atlasPanelOpen;
    if (typeof prefs.atlasPanelWidth === "number") panelWidth = clampWidth(prefs.atlasPanelWidth);
    if (typeof prefs.atlasTextScale === "number" && SCALE_STEPS[prefs.atlasTextScale]) scaleIndex = prefs.atlasTextScale;
    applyLayout();
  });

  // --- מצב ---

  let currentPhone = null; // הטלפון שמוצג כרגע (מזוהה מהשיחה או שהוקלד ידנית)
  let currentName = null; // השם כפי שמופיע בוואטסאפ
  let meta = null; // /meta - סטטוסים, משתמשות, סניפים, תגיות קיימות
  let data = null; // /lookup האחרון
  let errorMessage = "";
  let lookupSeq = 0; // כדי שתשובה ישנה (משיחה קודמת) לא תדרוס את הנוכחית
  const openSections = new Set(["notes", "tasks"]);
  const ui = { createLead: false, addTag: false };

  const text = (value) => (value === null || value === undefined || value === "" ? "" : escapeHtml(value));

  function kv(label, valueHtml) {
    if (valueHtml === null || valueHtml === undefined || valueHtml === "") return "";
    return `<div class="kv"><div class="kv-label">${escapeHtml(label)}</div><div class="kv-value">${valueHtml}</div></div>`;
  }

  function badge(label, color) {
    return `<span class="badge" style="background:${escapeHtml(color)}">${escapeHtml(label)}</span>`;
  }

  const EXTERNAL_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>`;

  const TAG_COLORS = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0d9488", "#4d7c0f", "#b45309", "#0369a1"];
  function tagColor(tag) {
    let hash = 0;
    for (const ch of tag) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    return TAG_COLORS[hash % TAG_COLORS.length];
  }

  function formatDateTime(iso) {
    if (!iso) return "";
    const [date, time = ""] = iso.split("T");
    const [y, m, d] = date.split("-");
    return `${d}/${m}/${y.slice(2)} ${time.slice(0, 5)}`.trim();
  }

  function formatDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.slice(0, 10).split("-");
    return `${d}/${m}/${y}`;
  }

  function todayIso() {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  }

  function setBody(html) {
    bodyEl.innerHTML = (errorMessage ? `<div class="error">${escapeHtml(errorMessage)}</div>` : "") + html;
  }

  function renderLoading() {
    setBody(`<p class="muted">טוען...</p>`);
  }

  function renderLoginRequired() {
    setBody(`
      <p>צריך להתחבר לתוסף.</p>
      <p class="muted">לחצי על סמל התוסף למעלה בדפדפן והתחברי עם שם המשתמש והסיסמה שלך מה-CRM.</p>
    `);
  }

  function renderManualPhoneBox() {
    setBody(`
      <p class="muted">לא זוהה מספר טלפון לשיחה הפתוחה (או שזו קבוצה).</p>
      <form class="manual-phone" data-form="manual-phone">
        <input type="text" name="phone" placeholder="מספר טלפון (05...)" />
        <button class="btn" type="submit">חפשי</button>
      </form>
    `);
  }

  // --- כרטיס איש הקשר ---

  function section(key, title, count, innerHtml) {
    const open = openSections.has(key) ? " open" : "";
    const countLabel = count === null || count === undefined ? "" : ` (${count})`;
    return `
      <div class="section${open}">
        <button class="section-head" data-action="toggle-section" data-section="${key}">
          <span>${escapeHtml(title)}${countLabel}</span><span class="chev">⌄</span>
        </button>
        <div class="section-body">${innerHtml}</div>
      </div>
    `;
  }

  function statusSelect(lead) {
    const statuses = (meta && meta.statuses) || [];
    const current = statuses.find((s) => s.name === lead.status);
    const color = (current && current.color) || "#999";
    const options = statuses
      .map((s) => `<option value="${escapeHtml(s.name)}"${s.name === lead.status ? " selected" : ""}>${escapeHtml(s.name)}</option>`)
      .join("");
    const unknown = lead.status && !current ? `<option selected>${escapeHtml(lead.status)}</option>` : "";
    return `<select class="status-select" data-action="status" style="border-color:${escapeHtml(color)}">${unknown}${options}</select>`;
  }

  function assignSelect(lead) {
    const users = (meta && meta.users) || [];
    const current = lead.assigned_user || "";
    const options = [`<option value="">ללא</option>`]
      .concat(users.map((u) => `<option value="${escapeHtml(u)}"${u === current ? " selected" : ""}>${escapeHtml(u)}</option>`));
    if (current && !users.includes(current)) options.push(`<option selected>${escapeHtml(current)}</option>`);
    return `<select data-action="assign">${options.join("")}</select>`;
  }

  function tagsHtml() {
    const chips = (data.tags || [])
      .map((tag) => `<span class="tag" style="background:${tagColor(tag)}">${escapeHtml(tag)}<button data-action="remove-tag" data-tag="${escapeHtml(tag)}" title="הסרה">×</button></span>`)
      .join("");
    if (ui.addTag) {
      const suggestions = ((meta && meta.tag_names) || []).map((t) => `<option value="${escapeHtml(t)}">`).join("");
      return `${chips}
        <form class="inline-form" data-form="add-tag">
          <input name="tag" list="atlas-tag-list" placeholder="שם התגית" maxlength="40" autocomplete="off" />
          <datalist id="atlas-tag-list">${suggestions}</datalist>
          <button class="btn" type="submit">הוספה</button>
          <button class="btn ghost" type="button" data-action="cancel-add-tag">ביטול</button>
        </form>`;
    }
    return `${chips}<button class="pill-btn" data-action="open-add-tag">+ הוסף תגית</button>`;
  }

  function createLeadHtml() {
    if (!ui.createLead) return `<button class="pill-btn" data-action="open-create-lead">+ צור ליד ב-CRM</button>`;
    const branches = (meta && meta.branches) || [];
    const suggestedName = (data.customer && data.customer.full_name) || (data.arbox_contact && data.arbox_contact.full_name) || currentName || "";
    return `
      <form class="stack-form" data-form="create-lead">
        <input name="full_name" placeholder="שם מלא" value="${escapeHtml(suggestedName)}" />
        <select name="branch">${branches.map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join("")}</select>
        <div style="display:flex; gap:6px">
          <button class="btn" type="submit">יצירת ליד</button>
          <button class="btn ghost" type="button" data-action="cancel-create-lead">ביטול</button>
        </div>
      </form>`;
  }

  function notesSection(lead) {
    if (!lead) return section("notes", "הערות", null, `<p class="muted">הערות נשמרות על הליד ב-CRM - צרי ליד כדי להוסיף.</p>`);
    const notes = (lead.notes || "").trim();
    const count = notes ? notes.split(/\n\s*\n/).filter(Boolean).length : 0;
    return section("notes", "הערות", count, `
      ${notes ? `<div class="notes-box">${escapeHtml(notes)}</div>` : `<p class="muted">אין הערות עדיין</p>`}
      <form class="stack-form" data-form="add-note">
        <textarea name="note" placeholder="הערה חדשה..."></textarea>
        <div><button class="btn" type="submit">הוסף הערה</button></div>
      </form>`);
  }

  function tasksSection() {
    const tasks = data.tasks || [];
    const today = todayIso();
    const rows = tasks.map((task) => {
      const overdue = !task.done && task.due_date && task.due_date < today;
      return `
        <div class="task${task.done ? " done" : ""}">
          <input type="checkbox" data-action="toggle-task" data-id="${task.id}"${task.done ? " checked" : ""} />
          <span class="task-title">${escapeHtml(task.title)}</span>
          ${task.due_date ? `<span class="task-due${overdue ? " overdue" : ""}">${formatDate(task.due_date)}</span>` : ""}
          <button class="x-btn" data-action="delete-task" data-id="${task.id}" title="מחיקה">×</button>
        </div>`;
    }).join("");
    const open = tasks.filter((t) => !t.done).length;
    return section("tasks", "משימות", open, `
      ${rows || `<p class="muted">אין משימות</p>`}
      <form class="stack-form" data-form="add-task">
        <input name="title" placeholder="משימה חדשה (למשל: לחזור אליה)" maxlength="200" />
        <div style="display:flex; gap:6px">
          <input name="due_date" type="date" />
          <button class="btn" type="submit">הוסף משימה</button>
        </div>
      </form>`);
  }

  function visitsSection() {
    const visits = data.recent_visits || [];
    const total = data.customer && data.customer.visits && data.customer.visits.visit_count;
    const rows = visits.map((visit) => {
      const checkIn = visit.check_in === "Yes" ? "הגיעה" : visit.check_in === "No" ? "לא הגיעה" : "";
      return `<div class="visit-row"><span>${formatDate(visit.visit_date)} ${escapeHtml(visit.visit_time || "")}</span>` +
        `<span>${escapeHtml(visit.class_name || "")}</span><span class="muted">${escapeHtml(checkIn)}</span></div>`;
    }).join("");
    const footer = total ? `<p class="muted">סה"כ ${escapeHtml(total)} כניסות שנספרו במערכת</p>` : "";
    return section("visits", "ביקורים", visits.length, (rows || `<p class="muted">אין ביקורים ב-45 הימים האחרונים</p>`) + footer);
  }

  function activitySection() {
    const items = data.activity || [];
    const rows = items.map((item) => `
      <div class="activity">${escapeHtml(item.text)}
        <div class="meta">${escapeHtml(item.username || "")} · ${formatDateTime(item.created_at)}</div>
      </div>`).join("");
    return section("activity", "יומן פעילות", items.length, rows || `<p class="muted">עוד אין פעילות מתועדת</p>`);
  }

  function renderCard() {
    const lead = data.lead;
    const customer = data.customer || {};
    const member = customer.member;
    const contact = data.arbox_contact;

    // סדר עדיפויות למקור הנתונים: לקוחה ב-Arbox, אחרת משתמשת Arbox אחרת (ליד/צוות/אגרגטור), אחרת CRM
    const source = member || contact ? "Arbox" : lead ? "CRM" : null;
    const displayName = (member && customer.full_name) || (contact && contact.full_name) || (lead && lead.full_name) || currentName || "";
    globalThis.AtlasCRM.contactFirstName = (displayName || "").trim().split(/\s+/)[0] || "";

    // כפתורי קישור קומפקטיים בצד שמאל של שורת השם (בעברית השם מימין)
    const pills = [];
    if (member || contact) {
      pills.push(`<button class="pill-link" data-action="open-arbox" title="כרטיס הלקוחה ב-Arbox">Arbox ${EXTERNAL_ICON}</button>`);
    }
    if (lead) {
      pills.push(`<a class="pill-link" href="${CRM_BASE}/leads/${encodeURIComponent(lead.id)}/edit" target="_blank" rel="noopener" title="הליד ב-CRM">CRM ${EXTERNAL_ICON}</a>`);
    }
    let html = `<div class="name-row"><div class="name">${text(displayName) || "ללא שם"}</div>` +
      (pills.length ? `<div class="pills">${pills.join("")}</div>` : "") + `</div>`;
    html += `<div class="source">${source ? `נתונים מ-${source}` : "לא נמצא ב-Arbox וב-CRM"}</div>`;

    if (member) {
      html += kv("סטטוס", member.active ? badge("לקוחה פעילה", "#27ae60") : badge("לא פעילה", "#95a5a6"));
    } else if (contact) {
      html += kv("סטטוס", badge(contact.role_label, "#64748b"));
    }
    html += lead ? kv(source === "CRM" ? "סטטוס" : "סטטוס ב-CRM", statusSelect(lead)) : kv("ליד ב-CRM", createLeadHtml());

    if (member) {
      html += kv("סוג מנוי", text(member.membership_type_name));
      html += kv("תוקף", customer.recurring ? "מתחדש (הוראת קבע)" : text(formatDate(member.membership_end_date)));
      html += kv("מחיר", member.membership_price ? `${text(member.membership_price)} ₪` : "");
      if (customer.has_debt) html += kv("חוב", `<span class="debt">${text(member.debt)} ₪</span>`);
    }
    html += kv("טלפון", text(data.phone));
    html += kv("מייל", text((member && member.email) || (contact && contact.email)));
    html += kv("סניף", text((member && customer.branch) || (contact && contact.branch) || (lead && lead.branch)));
    html += kv("גיל", text(customer.age || (contact && contact.age)));
    if (member) html += kv("לקוחה מאז", text(formatDate(member.member_since)));
    else if (contact) html += kv("ב-Arbox מאז", text(formatDate(contact.created_date)));
    html += kv("תגיות", tagsHtml());
    if (lead) {
      html += kv("נציג/ה", assignSelect(lead));
      html += kv("ערוץ הגעה", text(lead.channel));
    }

    html += visitsSection();
    html += notesSection(lead);
    html += tasksSection();
    html += activitySection();
    setBody(html);
  }

  // --- טעינה ---

  async function loadMeta() {
    const result = await api("/api/extension/meta");
    if (result.status === 200 && result.data.ok) meta = result.data;
    return result.status;
  }

  async function lookupPhone(phone, { quiet = false } = {}) {
    const seq = ++lookupSeq;
    if (!quiet) {
      errorMessage = "";
      ui.createLead = false;
      ui.addTag = false;
      renderLoading();
    }
    const auth = await sendToBackground({ type: "atlasAuthState" });
    if (!auth?.loggedIn) {
      meta = null;
      renderLoginRequired();
      return;
    }
    if (!meta && (await loadMeta()) === 401) {
      renderLoginRequired();
      return;
    }

    const result = await api(`/api/extension/lookup?phone=${encodeURIComponent(phone)}`);
    if (seq !== lookupSeq) return;
    if (result.status === 401) {
      meta = null;
      renderLoginRequired();
      return;
    }
    if (result.status !== 200 || !result.data.ok) {
      setBody(`<p class="muted">שגיאה בשליפת מידע: ${escapeHtml(result.data?.error || result.status)}</p>`);
      return;
    }
    currentPhone = result.data.phone;
    data = result.data;
    renderCard();
  }

  // פעולת כתיבה: שולחת לשרת, ואז טוענת מחדש את הכרטיס בשקט (כדי שגם יומן הפעילות יתעדכן)
  async function act(path, body) {
    errorMessage = "";
    const result = await api(path, { method: "POST", body: body || {} });
    if (result.status === 401) {
      meta = null;
      renderLoginRequired();
      return false;
    }
    if (result.status !== 200 || !result.data.ok) {
      errorMessage = result.data?.error || `שגיאה (${result.status})`;
      renderCard();
      return false;
    }
    await lookupPhone(currentPhone, { quiet: true });
    return true;
  }

  // --- אירועים (האצלה על גוף הפאנל - הוא נבנה מחדש בכל רינדור) ---

  bodyEl.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target || target.tagName === "SELECT") return;
    const action = target.dataset.action;

    if (action === "toggle-section") {
      const key = target.dataset.section;
      if (openSections.has(key)) openSections.delete(key);
      else openSections.add(key);
      target.closest(".section").classList.toggle("open");
    } else if (action === "open-add-tag" || action === "cancel-add-tag") {
      ui.addTag = action === "open-add-tag";
      renderCard();
      if (ui.addTag) shadow.querySelector('[data-form="add-tag"] input')?.focus();
    } else if (action === "open-create-lead" || action === "cancel-create-lead") {
      ui.createLead = action === "open-create-lead";
      renderCard();
    } else if (action === "open-arbox") {
      target.disabled = true;
      const result = await sendToBackground({ type: "atlasOpenArboxProfile", phone: currentPhone });
      if (result.status !== 200) {
        errorMessage = result.data?.error || "לא הצלחתי לפתוח את הכרטיס ב-Arbox";
      }
      renderCard();
    } else if (action === "remove-tag") {
      await act(`/api/extension/contacts/${currentPhone}/tags/remove`, { tag: target.dataset.tag });
    } else if (action === "toggle-task") {
      await act(`/api/extension/tasks/${target.dataset.id}/toggle`);
    } else if (action === "delete-task") {
      await act(`/api/extension/tasks/${target.dataset.id}/delete`);
    }
  });

  bodyEl.addEventListener("change", async (event) => {
    const target = event.target;
    if (!data || !data.lead) return;
    if (target.dataset.action === "status") {
      await act(`/api/extension/leads/${data.lead.id}/status`, { status: target.value });
    } else if (target.dataset.action === "assign") {
      await act(`/api/extension/leads/${data.lead.id}/assign`, { assigned_user: target.value });
    }
  });

  bodyEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const fields = Object.fromEntries(new FormData(form).entries());
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;

    const kind = form.dataset.form;
    if (kind === "manual-phone") {
      if ((fields.phone || "").trim()) await lookupPhone(fields.phone.trim());
    } else if (kind === "add-tag") {
      if (!(fields.tag || "").trim()) return void (button.disabled = false);
      ui.addTag = false;
      await act(`/api/extension/contacts/${currentPhone}/tags`, { tag: fields.tag });
      await loadMeta(); // תגית חדשה - להשלמה האוטומטית בפעם הבאה
    } else if (kind === "create-lead") {
      ui.createLead = false;
      await act("/api/extension/leads", { phone: currentPhone, full_name: fields.full_name, branch: fields.branch });
    } else if (kind === "add-note") {
      if (!(fields.note || "").trim()) return void (button.disabled = false);
      await act(`/api/extension/leads/${data.lead.id}/notes`, { note: fields.note });
    } else if (kind === "add-task") {
      if (!(fields.title || "").trim()) return void (button.disabled = false);
      await act(`/api/extension/contacts/${currentPhone}/tasks`, { title: fields.title, due_date: fields.due_date });
    }
  });

  // --- זיהוי השיחה הפעילה (מ-content-world.js) ---

  function handleActiveChat(info) {
    if (!info || !info.phone) {
      currentPhone = null;
      data = null;
      globalThis.AtlasCRM.contactFirstName = "";
      sendToBackground({ type: "atlasAuthState" }).then((auth) => {
        if (!auth?.loggedIn) renderLoginRequired();
        else renderManualPhoneBox();
      });
      return;
    }
    currentName = info.name;
    lookupPhone(info.phone);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (event.data?.source !== "atlas-wa-world" || event.data.type !== "activeChat") return;
    console.info(`${LOG} active chat:`, event.data.info);
    handleActiveChat(event.data.info);
  });

  // התחברות/התנתקות מהפופאפ - לטעון מחדש בלי שתצטרכי לרענן את וואטסאפ
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !changes.token) return;
    meta = null;
    window.postMessage({ source: "atlas-wa-isolated", type: "requestActiveChat" }, "*");
  });

  refreshBtn.addEventListener("click", () => {
    meta = null;
    if (currentPhone) lookupPhone(currentPhone);
    else window.postMessage({ source: "atlas-wa-isolated", type: "requestActiveChat" }, "*");
  });

  // בקשה ראשונית (ה-world script גם שולח לבד כל שנייה, אבל לא מחכים לטיק הראשון)
  setTimeout(() => {
    window.postMessage({ source: "atlas-wa-isolated", type: "requestActiveChat" }, "*");
  }, 1500);

  renderLoading();
})();

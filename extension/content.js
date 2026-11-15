// רץ ב-"isolated world" הרגיל (ברירת המחדל) - יש לו גישה מלאה ל-DOM של הדף (אפשר להזריק
// אליו אלמנטים, לקרוא/לכתוב בתיבת הכתיבה וכו'), אבל לא למשתני JS הפנימיים של וואטסאפ עצמה -
// זו הסיבה ש-content-world.js (world: "MAIN") רץ בנפרד ומתקשר לכאן דרך window.postMessage.
// שלב זה (תצוגה בלבד): מציג מידע, בלי פעולות כתיבה - אלה יתווספו בשלב הבא
(function () {
  const LOG = "[AtlasCRM]";

  function sendToBackground(message) {
    return chrome.runtime.sendMessage(message);
  }

  function apiRequest(path, options) {
    return sendToBackground({ type: "atlasApiRequest", path, options });
  }

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
        position: fixed;
        top: 0;
        left: 0;
        height: 100vh;
        width: 340px;
        background: #fff;
        border-left: 1px solid #ddd;
        box-shadow: 2px 0 10px rgba(0,0,0,0.08);
        direction: rtl;
        display: flex;
        flex-direction: column;
        transform: translateX(-340px);
        transition: transform 0.2s ease;
        font-size: 13px;
        color: #111;
      }
      .panel.open { transform: translateX(0); }
      .toggle {
        position: fixed;
        top: 70px;
        left: 0;
        background: #2563eb;
        color: #fff;
        border: none;
        border-radius: 0 6px 6px 0;
        padding: 10px 6px;
        cursor: pointer;
        writing-mode: vertical-rl;
        font-size: 12px;
        transition: left 0.2s ease;
      }
      .toggle.open { left: 340px; }
      .header {
        padding: 12px 14px;
        border-bottom: 1px solid #eee;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .header h2 { font-size: 14px; margin: 0; }
      .refresh-btn {
        border: none;
        background: none;
        cursor: pointer;
        font-size: 14px;
        color: #2563eb;
      }
      .body { padding: 14px; overflow-y: auto; flex: 1; }
      .row { margin-bottom: 10px; }
      .label { color: #888; font-size: 11px; margin-bottom: 2px; }
      .value { font-size: 13px; }
      .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        color: #fff;
        font-size: 12px;
      }
      .section-title {
        font-weight: bold;
        margin: 16px 0 6px;
        font-size: 12px;
        color: #444;
        border-bottom: 1px solid #eee;
        padding-bottom: 4px;
      }
      .notes-box {
        white-space: pre-wrap;
        background: #f9f9f9;
        border-radius: 6px;
        padding: 8px;
        max-height: 140px;
        overflow-y: auto;
        font-size: 12px;
      }
      .visit-row {
        display: flex;
        justify-content: space-between;
        padding: 5px 0;
        border-bottom: 1px solid #f0f0f0;
        font-size: 12px;
      }
      .muted { color: #999; font-size: 12px; }
      .manual-phone {
        display: flex;
        gap: 6px;
        margin-top: 8px;
      }
      .manual-phone input {
        flex: 1;
        padding: 6px 8px;
        border: 1px solid #ccc;
        border-radius: 6px;
        font-size: 12px;
      }
      .manual-phone button, .link-btn {
        padding: 6px 10px;
        border: none;
        border-radius: 6px;
        background: #2563eb;
        color: #fff;
        cursor: pointer;
        font-size: 12px;
      }
      a { color: #2563eb; }
      .name { font-size: 16px; font-weight: bold; margin-bottom: 12px; }
      .kv {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 12px;
        padding: 6px 0;
        border-bottom: 1px solid #f3f3f3;
      }
      .kv-label { color: #888; font-size: 12px; flex-shrink: 0; }
      .kv-value { font-size: 13px; text-align: left; word-break: break-word; }
      .debt { color: #dc2626; font-weight: bold; }
      .crm-link { display: inline-block; margin-top: 10px; font-size: 12px; }
    </style>
    <button class="toggle">CRM</button>
    <div class="panel">
      <div class="header">
        <h2>מידע לקוח</h2>
        <button class="refresh-btn" title="רענון">⟳</button>
      </div>
      <div class="body"></div>
    </div>
  `;

  const panelEl = shadow.querySelector(".panel");
  const toggleEl = shadow.querySelector(".toggle");
  const bodyEl = shadow.querySelector(".body");
  const refreshBtn = shadow.querySelector(".refresh-btn");

  let panelOpen = true;
  function setOpen(open) {
    panelOpen = open;
    panelEl.classList.toggle("open", open);
    toggleEl.classList.toggle("open", open);
  }
  setOpen(true);
  toggleEl.addEventListener("click", () => setOpen(!panelOpen));

  // --- מצב ---

  let currentPhone = null;
  let currentName = null;

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function render(html) {
    bodyEl.innerHTML = html;
  }

  function renderLoading() {
    render(`<p class="muted">טוען...</p>`);
  }

  function renderLoginRequired() {
    render(`
      <p>צריך להתחבר לתוסף.</p>
      <p class="muted">לחצי על סמל התוסף למעלה בדפדפן והתחברי עם שם המשתמש והסיסמה שלך מה-CRM.</p>
    `);
  }

  function renderManualPhoneBox(message) {
    return `
      <p class="muted">${escapeHtml(message || "לא זוהה מספר טלפון אוטומטית לשיחה הפתוחה.")}</p>
      <div class="manual-phone">
        <input type="text" placeholder="הכניסי מספר טלפון (05...)" id="manual-phone-input" />
        <button id="manual-phone-btn">חפשי</button>
      </div>
    `;
  }

  function formatVisit(visit) {
    const checkIn = visit.check_in === "Yes" ? "הגיעה" : visit.check_in === "No" ? "לא הגיעה" : "";
    return `
      <div class="visit-row">
        <span>${escapeHtml(visit.visit_date || "")} ${escapeHtml(visit.visit_time || "")}</span>
        <span>${escapeHtml(visit.class_name || "")}</span>
        <span class="muted">${escapeHtml(checkIn)}</span>
      </div>
    `;
  }

  function kv(label, valueHtml) {
    if (valueHtml === null || valueHtml === undefined || valueHtml === "") return "";
    return `<div class="kv"><div class="kv-label">${escapeHtml(label)}</div><div class="kv-value">${valueHtml}</div></div>`;
  }

  function text(value) {
    return value === null || value === undefined || value === "" ? "" : escapeHtml(value);
  }

  function renderLookupResult(data) {
    const lead = data.lead;
    const customer = data.customer || {};
    const member = customer.member || data.membership;
    const visits = data.recent_visits || [];
    const statusColors = data.status_colors || {};

    const displayName = (lead && lead.full_name) || customer.full_name || currentName || "";

    // סטטוס: ליד ב-CRM קודם (עם הצבע שלו), אחרת מצב המנוי ב-Arbox
    let statusHtml = "";
    if (lead && lead.status) {
      const color = statusColors[lead.status] || "#999";
      statusHtml = `<span class="badge" style="background:${escapeHtml(color)}">${escapeHtml(lead.status)}</span>`;
    } else if (member) {
      statusHtml = member.active
        ? `<span class="badge" style="background:#27ae60">לקוחה פעילה</span>`
        : `<span class="badge" style="background:#95a5a6">לא פעילה</span>`;
    } else {
      statusHtml = `<span class="badge" style="background:#bbb">לא במערכת</span>`;
    }

    let membershipEnd = "";
    if (member) {
      membershipEnd = customer.recurring ? "מתחדש (הוראת קבע)" : text(member.membership_end_date);
    }

    let html = `<div class="name">${text(displayName) || "ללא שם"}</div>`;
    html += kv("סטטוס", statusHtml);
    html += kv("סוג מנוי", member ? text(member.membership_type_name) : "");
    html += kv("תוקף", membershipEnd);
    html += kv("מחיר", member && member.membership_price ? `${text(member.membership_price)} ₪` : "");
    html += customer.has_debt ? kv("חוב", `<span class="debt">${text(member.debt)} ₪</span>`) : "";
    html += kv("טלפון", text(data.phone));
    html += kv("מייל", member ? text(member.email) : "");
    html += kv("סניף", text((lead && lead.branch) || customer.branch));
    html += kv("גיל", text(customer.age));
    html += kv("לקוחה מאז", member ? text(member.member_since) : "");
    html += kv("נציג/ה", lead ? text(lead.assigned_user) : "");
    html += kv("ערוץ הגעה", lead ? text(lead.channel) : "");

    if (lead) {
      html += `<a class="crm-link" href="https://eytan1985.pythonanywhere.com/leads/${encodeURIComponent(lead.id)}/edit" target="_blank" rel="noopener">פתיחה ב-CRM ↗</a>`;
      html += `<div class="section-title">הערות</div>`;
      html += `<div class="notes-box">${text(lead.notes) || "אין הערות"}</div>`;
    } else if (!member) {
      html += `<p class="muted">המספר הזה לא ליד ב-CRM ולא לקוחה ב-Arbox (יכול להיות גם איש/אשת צוות).</p>`;
    }

    const totalVisits = customer.visits && customer.visits.visit_count;
    html += `<div class="section-title">ביקורים${totalVisits ? ` (${escapeHtml(totalVisits)} סה"כ)` : ""}</div>`;
    html += visits.length ? visits.map(formatVisit).join("") : `<p class="muted">אין ביקורים ב-45 הימים האחרונים</p>`;

    render(html);
  }

  async function lookupPhone(phone) {
    renderLoading();
    const auth = await sendToBackground({ type: "atlasAuthState" });
    if (!auth?.loggedIn) {
      renderLoginRequired();
      return;
    }

    const result = await apiRequest(`/api/extension/lookup?phone=${encodeURIComponent(phone)}`, { method: "GET" });
    if (result.status === 401) {
      renderLoginRequired();
      return;
    }
    if (result.status !== 200 || !result.data.ok) {
      render(`<p class="muted">שגיאה בשליפת מידע: ${escapeHtml(result.data?.error || result.status)}</p>`);
      return;
    }
    renderLookupResult(result.data);
  }

  async function handleActiveChat(info) {
    if (!info || !info.phone) {
      currentPhone = null;
      const auth = await sendToBackground({ type: "atlasAuthState" });
      if (!auth?.loggedIn) {
        renderLoginRequired();
      } else {
        render(renderManualPhoneBox());
        bindManualPhoneHandlers();
      }
      return;
    }
    currentPhone = info.phone;
    currentName = info.name;
    await lookupPhone(info.phone);
  }

  function bindManualPhoneHandlers() {
    const input = shadow.querySelector("#manual-phone-input");
    const btn = shadow.querySelector("#manual-phone-btn");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const value = (input.value || "").trim();
      if (value) lookupPhone(value);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") btn.click();
    });
  }

  // --- קבלת זיהוי הצ'אט הפעיל מ-content-world.js ---

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (event.data?.source !== "atlas-wa-world") return;
    if (event.data.type === "activeChat") {
      console.info(`${LOG} active chat info:`, event.data.info);
      handleActiveChat(event.data.info);
    }
  });

  refreshBtn.addEventListener("click", () => {
    window.postMessage({ source: "atlas-wa-isolated", type: "requestActiveChat" }, "*");
  });

  // בקשה ראשונית (ה-world script גם שולח לבד כל שנייה, אבל לא מחכים לטיק הראשון)
  setTimeout(() => {
    window.postMessage({ source: "atlas-wa-isolated", type: "requestActiveChat" }, "*");
  }, 1500);

  renderLoading();
})();

import json

import anthropic

from atlas.paths import secret

API_KEY_FILE = secret(".anthropic_api_key")
CONVERSATIONS_FILE = secret(".whatsapp_conversations.json")

MODEL = "claude-sonnet-5"
MAX_RESULTS = 20
MAX_HISTORY_TURNS = 10
MAX_TOOL_LOOPS = 5


def load_api_key():
    if not API_KEY_FILE.exists():
        return None
    value = API_KEY_FILE.read_text().strip()
    return value or None


# היסטוריית שיחה קצרה לכל מספר טלפון (רק טקסט סופי, בלי בלוקים של tool_use) - כדי
# שאפשר יהיה לשאול שאלות המשך ("ותעדכן גם את הטלפון שממנו דיברנו") בלי לאבד הקשר,
# בלי לשמור עומק שלם של שרשרת קריאות כלים בין הודעה להודעה
def _load_all_conversations():
    if not CONVERSATIONS_FILE.exists():
        return {}
    try:
        return json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError):
        return {}


def _save_all_conversations(conversations):
    CONVERSATIONS_FILE.write_text(json.dumps(conversations, ensure_ascii=False), encoding="utf-8")


def _load_history(phone):
    return _load_all_conversations().get(phone, [])


def _append_history(phone, user_text, assistant_text):
    conversations = _load_all_conversations()
    history = conversations.get(phone, [])
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_text})
    conversations[phone] = history[-(MAX_HISTORY_TURNS * 2):]
    _save_all_conversations(conversations)


TOOLS = [
    {
        "name": "search_leads",
        "description": "מחפש לידים לפי סינון אופציונלי (אפשר לשלב כמה סינונים יחד). מחזיר עד 20 תוצאות ואת הכמות הכוללת שתואמת.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "סינון לפי סטטוס מדויק"},
                "phone": {"type": "string", "description": "סינון לפי חלק ממספר טלפון"},
                "assigned_user": {"type": "string", "description": "סינון לפי שם המשתמש המטפל (מנהל לקוח)"},
                "channel": {"type": "string", "description": "סינון לפי ערוץ (למשל פייסבוק, Google Ads)"},
            },
        },
    },
    {
        "name": "lead_status_counts",
        "description": "מחזיר כמות לידים לכל סטטוס. שימושי לשאלות כלליות כמו 'כמה לידים חדשים יש לי' או 'תן לי סיכום מצב הלידים'.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_customers",
        "description": "מחפש לקוחות קיימים (לא לידים) לפי שם או טלפון.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "phone": {"type": "string"},
            },
        },
    },
    {
        "name": "search_appointments",
        "description": "מחפש תורים. אפשר לסנן לפי טלפון, או לבקש רק את תורי היום.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "today_only": {"type": "boolean"},
            },
        },
    },
    {
        "name": "update_lead_status",
        "description": "מעדכן את הסטטוס של ליד קיים. יש להשתמש רק בסטטוסים שמופיעים ברשימת הסטטוסים הזמינים (ניתן לבדוק אותם קודם עם lead_status_counts). בצע פעולה זו רק כשהמשתמש מבקש זאת במפורש.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "integer"},
                "new_status": {"type": "string"},
            },
            "required": ["lead_id", "new_status"],
        },
    },
    {
        "name": "assign_lead",
        "description": "משייך ליד למשתמש מטפל (מנהל לקוח), או מבטל שיוך אם assigned_user ריק. בצע פעולה זו רק כשהמשתמש מבקש זאת במפורש.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "integer"},
                "assigned_user": {"type": "string"},
            },
            "required": ["lead_id"],
        },
    },
]


def _lead_summary(record):
    return {
        "id": record.get("id"),
        "full_name": record.get("full_name"),
        "phone": record.get("phone"),
        "status": record.get("status"),
        "channel": record.get("channel"),
        "branch": record.get("branch"),
        "assigned_user": record.get("assigned_user"),
        "notes": record.get("notes"),
    }


def _filter_contains(df, column, value):
    return df[df[column].fillna("").astype(str).str.contains(value, case=False, na=False)]


def _execute_tool(repos, statuses, name, tool_input):
    if name == "search_leads":
        df = repos.leads.get_all()
        if tool_input.get("status"):
            df = df[df["status"] == tool_input["status"]]
        if tool_input.get("phone"):
            df = _filter_contains(df, "phone", tool_input["phone"])
        if tool_input.get("assigned_user"):
            df = df[df["assigned_user"].fillna("") == tool_input["assigned_user"]]
        if tool_input.get("channel"):
            df = df[df["channel"] == tool_input["channel"]]
        records = df.head(MAX_RESULTS).to_dict("records")
        return {"count_total": len(df), "results": [_lead_summary(r) for r in records]}

    if name == "lead_status_counts":
        df = repos.leads.get_all()
        counts = df["status"].value_counts().to_dict() if not df.empty else {}
        return {"counts": counts, "available_statuses": statuses}

    if name == "search_customers":
        df = repos.customers.get_all()
        if tool_input.get("name"):
            df = _filter_contains(df, "name", tool_input["name"])
        if tool_input.get("phone"):
            df = _filter_contains(df, "phone", tool_input["phone"])
        records = df.head(MAX_RESULTS).to_dict("records")
        return {"count_total": len(df), "results": records}

    if name == "search_appointments":
        if tool_input.get("today_only"):
            df = repos.appointments.get_today()
        elif tool_input.get("phone"):
            df = repos.appointments.get_by_phone(tool_input["phone"])
        else:
            df = repos.appointments.get_all()
        records = df.head(MAX_RESULTS).to_dict("records")
        return {"count_total": len(df), "results": records}

    if name == "update_lead_status":
        lead_id = tool_input.get("lead_id")
        new_status = tool_input.get("new_status")
        if new_status not in statuses:
            return {"error": f"סטטוס לא קיים: {new_status}. סטטוסים זמינים: {statuses}"}
        lead = repos.leads.get_by_id(lead_id)
        if lead is None:
            return {"error": f"ליד {lead_id} לא נמצא"}
        repos.leads.update_field(lead_id, "status", new_status)
        return {"success": True, "lead_id": lead_id, "new_status": new_status}

    if name == "assign_lead":
        lead_id = tool_input.get("lead_id")
        assigned_user = tool_input.get("assigned_user", "")
        lead = repos.leads.get_by_id(lead_id)
        if lead is None:
            return {"error": f"ליד {lead_id} לא נמצא"}
        repos.leads.update_field(lead_id, "assigned_user", assigned_user)
        return {"success": True, "lead_id": lead_id, "assigned_user": assigned_user}

    return {"error": f"unknown tool: {name}"}


SYSTEM_PROMPT = (
    "את/ה עוזר/ת אישי/ת לבעל/ת עסק שמנהל/ת CRM לתורים, לידים ולקוחות (עסק כושר/הרזיה). "
    "עונה בעברית, בקצרה ולעניין, בהתאמה לצ'אט וואטסאפ (בלי כותרות מיותרות). "
    "יש לך גישה לכלים לשליפת נתונים אמיתיים מהמערכת - תמיד להשתמש בהם, לא לנחש או להמציא נתונים. "
    "אפשר גם לבצע פעולות מוגבלות (עדכון סטטוס ליד, שיוך ליד למטפל) - יש לבצע אותן רק כשהמשתמש מבקש "
    "זאת במפורש, ותמיד לאשר בקצרה בסוף מה בוצע בפועל."
)


# עונה על שאלה אחת מהוואטסאפ, כולל לולאת tool-use מלאה מול Claude. שומרת/טוענת היסטוריית
# שיחה קצרה לפי מספר הטלפון כדי לשמור הקשר בין הודעות עוקבות
def answer_question(repos, statuses, phone, user_text):
    api_key = load_api_key()
    if not api_key:
        return "לא הוגדר מפתח API של Claude בצד השרת - יש להגדיר אותו קודם."

    client = anthropic.Anthropic(api_key=api_key)

    messages = list(_load_history(phone))
    messages.append({"role": "user", "content": user_text})

    final_text = "משהו השתבש בעיבוד הבקשה, נסה שוב."
    for _ in range(MAX_TOOL_LOOPS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text_parts = [block.text for block in response.content if block.type == "text"]
            final_text = "\n".join(text_parts).strip() or "לא הצלחתי להבין, אפשר לנסח מחדש?"
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _execute_tool(repos, statuses, block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    _append_history(phone, user_text, final_text)
    return final_text

import base64

import requests

from atlas.paths import secret

API_KEY_FILE = secret(".gemini_api_key")
API_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-3.6-flash"


def load_api_key():
    if not API_KEY_FILE.exists():
        return None
    value = API_KEY_FILE.read_text().strip()
    return value or None


# קריאה בודדת ל-Gemini (generateContent) - system prompt + היסטוריית שיחה (contents,
# בפורמט של Gemini: [{"role": "user"/"model", "parts": [...]}]) + כלים אופציונליים
# (function declarations). לא מכילה שום לוגיקת לולאת-כלים - זה נשאר באחריות הקורא
# (customer_assistant.py), כדי שהמודול הזה יישאר רק "קריאת API בודדת" ולא ידע על
# הלוגיקה העסקית. מחזירה את ה-JSON הגולמי של Gemini
def generate(system_prompt, contents, tools=None):
    api_key = load_api_key()
    if not api_key:
        return None

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
    }
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]

    response = requests.post(
        f"{API_BASE}/models/{MODEL}:generateContent",
        params={"key": api_key},
        json=body,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


# שולפת את החלקים (parts) של התשובה הראשונה מהמודל - כל חלק הוא טקסט ({"text": ...})
# או קריאת כלי ({"functionCall": {"name": ..., "args": {...}}})
def extract_parts(response_json):
    if not response_json:
        return []
    candidates = response_json.get("candidates") or []
    if not candidates:
        return []
    return candidates[0].get("content", {}).get("parts") or []


def extract_text(response_json):
    parts = extract_parts(response_json)
    text_parts = [part["text"] for part in parts if "text" in part]
    return "\n".join(text_parts).strip()


def extract_function_calls(response_json):
    parts = extract_parts(response_json)
    return [part["functionCall"] for part in parts if "functionCall" in part]


# קריאה גנרית ל-Gemini עם מדיה בודדת (אודיו/תמונה) כ-inline_data (base64) + הנחיה טקסטואלית -
# הבסיס המשותף ל-transcribe_audio/describe_sticker למטה. מחזירה None אם אין מפתח API/הקריאה
# נכשלה, כדי שהקורא יוכל ליפול חזרה בעדינות. mime_type לפעמים מגיע עם פרמטר נוסף מוואטסאפ
# ("audio/ogg; codecs=opus") - Gemini מצפה רק לסוג הבסיסי, אז חותכים לפני ה-";"
def _describe_media(file_bytes, mime_type, default_mime, instruction):
    api_key = load_api_key()
    if not api_key:
        return None

    base_mime = (mime_type or default_mime).split(";")[0].strip()
    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": instruction},
                {"inline_data": {"mime_type": base_mime, "data": base64.b64encode(file_bytes).decode("ascii")}},
            ],
        }],
    }
    response = requests.post(
        f"{API_BASE}/models/{MODEL}:generateContent",
        params={"key": api_key},
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    return extract_text(response.json())


# מתמללת הודעה קולית נכנסת מוואטסאפ - Gemini תומך באודיו ישירות כ-inline_data, בלי צורך
# בשירות תמלול נפרד
def transcribe_audio(file_bytes, mime_type):
    return _describe_media(
        file_bytes, mime_type, "audio/ogg",
        "תמלל/י את ההודעה הקולית הזו לעברית. החזר/י רק את התמלול עצמו, בלי שום הקדמה, הערה או סימון נוסף.",
    )


# מתארת בקצרה סטיקר נכנס מוואטסאפ - Gemini תומך גם בתמונות כ-inline_data (סטיקר הוא קובץ
# תמונה, בד"כ image/webp). התיאור מוזן לבוט כהקשר (לא כטקסט מהלקוח/ה עצמו/ה) כדי שיוכל
# להבין את הכוונה/הרגש שהביעו בסטיקר ולהגיב בהתאם
def describe_sticker(file_bytes, mime_type):
    return _describe_media(
        file_bytes, mime_type, "image/webp",
        "תארי בעברית, במשפט קצר אחד, מה רואים בסטיקר הזה (הבעה/רגש/אימוג'י/טקסט אם יש) - "
        "בלי שום הקדמה או הערה נוספת.",
    )

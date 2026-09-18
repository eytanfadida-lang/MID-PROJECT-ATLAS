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

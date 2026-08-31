from pathlib import Path

# עוגן יציב לשורש הפרויקט - לא תלוי בספריית העבודה (CWD) של מי שמריץ את הקוד.
# זה בדיוק מה שהיה חסר קודם: arbox_run_sync.py נאלץ לעשות os.chdir בעצמו כי כל
# שאר הקוד פותח קבצים לפי נתיב יחסי ל-CWD ולא לפי מיקום הפרויקט בפועל - עבד
# במקרה בפייתון-אנywhere רק כי ה-CWD שם תמיד זהה לתיקיית הפרויקט
PROJECT_ROOT = Path(__file__).resolve().parent


def secret(name):
    """נתיב לקובץ סוד/טוקן/מצב מקומי בשורש הפרויקט (למשל '.flask_secret')."""
    return PROJECT_ROOT / name


def data(name):
    """נתיב לקובץ נתונים בשורש הפרויקט (למשל 'appointments.db')."""
    return PROJECT_ROOT / name

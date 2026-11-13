# Dockerfile לבדיקה מקומית עקבית: בונה סביבה נקייה ומריץ בה import + pytest,
# בדיוק כמו ה-CI (.github/workflows/ci.yml) - "האם הקוד עדיין עובד?" בלי תלות
# בתיקיית הפיתוח המקומית (שכבר מלאה בסודות/DB אמיתיים שאסור שיגיעו לתמונה).
#
# הפריסה בפועל היא ב-PythonAnywhere (git pull + Reload, לא קונטיינרים) - זה כלי
# פיתוח/בדיקה מקומי בלבד, לא חלק מהפריסה.

FROM python:3.11-slim

WORKDIR /app

# מעתיקים קודם רק את requirements.txt כדי לנצל Docker layer caching:
# אם הקוד משתנה אבל התלויות לא, השכבה הזו לא תיבנה מחדש
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# עכשיו מעתיקים את שאר הקוד (מה שמוחרג ב-.dockerignore - סודות, DB אמיתי,
# .git וכו' - לעולם לא מגיע לתוך התמונה)
COPY . .

# תרגול אבטחה בסיסי: לא מריצים את הקונטיינר כ-root
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# פקודת ברירת המחדל: אותה בדיקה כמו ב-CI - import נקי של app.py, ואז pytest.
# ה-DB/סוד נוצרים אוטומטית בתוך הקונטיינר (self-heal, ראו auth.py/db_context.py)
# ונעלמים כשהוא נסגר - זה בדיוק הרצוי לבדיקה חד-פעמית, לא לנתונים אמיתיים
CMD ["sh", "-c", "python -c 'import app' && python -m pytest -q"]

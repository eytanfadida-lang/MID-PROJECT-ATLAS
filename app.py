import os

from atlas.factory import create_app, start_arbox_sync_scheduler, ARBOX_AUTO_SYNC_ENABLED

# PythonAnywhere (ה-WSGI config) עושה from app import app as application - חייב להישאר
# בשם ובנתיב הזה בדיוק. כל הלוגיקה בפועל נמצאת ב-atlas/ (ראו atlas/__init__.py:create_app)
app = create_app()

if __name__ == "__main__":
    DEBUG_MODE = True
    # ב-debug=True ה-reloader מריץ גם תהליך "צג" נוסף; מפעילים את הלולאה רק בתהליך העבודה בפועל
    if ARBOX_AUTO_SYNC_ENABLED and (not DEBUG_MODE or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        start_arbox_sync_scheduler(app)
    app.run(host="127.0.0.1", port=5000, debug=DEBUG_MODE)

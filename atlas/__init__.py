# במכוון ריק (לא מייבא מ-atlas.factory כאן). Python מריץ את ה-__init__.py של חבילה בכל פעם
# שמייבאים תת-מודול שלה, אז אילו create_app (ותלויות ה-Flask/anthropic הכבדות שהוא גורר)
# היו מיובאים כאן - כל ייבוא ולו יחיד תחת atlas.* (למשל atlas.paths או atlas.integrations.arbox.client
# מתוך scripts/cron קטנים כמו arbox_push_sync.py) היה מפעיל את כל שרשרת הייבוא הזו בשוגג.
# זה בדיוק מה שהיה שובר את ה-GitHub Action של סנכרון Arbox, שמתקין רק requests ולא flask/anthropic

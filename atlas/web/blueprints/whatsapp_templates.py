import re

from flask import Blueprint, render_template, redirect, url_for, flash, request

from atlas.core.auth import admin_required
from atlas.integrations.whatsapp import bot as whatsapp_bot

# עמוד ליצירה/מעקב של תבניות הודעת וואטסאפ מאושרות מראש - בניגוד לטקסט חופשי (ראו
# atlas/automations/engine.py, _is_within_whatsapp_window), תבנית מאושרת מגיעה גם מחוץ
# לחלון 24 השעות. Meta היא מקור האמת היחיד לרשימה/לסטטוס - אין שום שמירה מקומית, כל טעינת
# עמוד שולפת מחדש. השליחה בפועל דרך תבנית (חיבור לאוטומציות) היא שלב נפרד, לא כאן עדיין
bp = Blueprint("whatsapp_templates", __name__, url_prefix="/whatsapp-templates")

_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
_CATEGORIES = ("MARKETING", "UTILITY")

_STATUS_LABELS = {
    "APPROVED": "מאושרת",
    "PENDING": "ממתינה לאישור",
    "REJECTED": "נדחתה",
    "DISABLED": "מושבתת",
    "PAUSED": "מושהית",
}


@bp.route("/")
@admin_required
def list_templates():
    config = whatsapp_bot.CUSTOMER_BOT
    error = None
    templates = []
    if not whatsapp_bot.load_waba_id(config):
        error = "לא הוגדר מזהה WABA (.whatsapp_customer_waba_id) - אי אפשר לשלוף/ליצור תבניות."
    else:
        try:
            templates = whatsapp_bot.list_message_templates(config)
        except Exception as exc:
            error = f"שליפת התבניות מ-Meta נכשלה: {exc}"
    return render_template(
        "whatsapp_templates/index.html", templates=templates, error=error,
        status_labels=_STATUS_LABELS, form={},
    )


@bp.route("/new", methods=["POST"])
@admin_required
def create_template():
    config = whatsapp_bot.CUSTOMER_BOT
    name = request.form.get("name", "").strip().lower()
    category = request.form.get("category", "")
    body_text = request.form.get("body_text", "").strip()
    footer_text = request.form.get("footer_text", "").strip()
    example_values = [
        value.strip() for value in request.form.getlist("example_values") if value.strip()
    ]

    error = None
    if not name or not _NAME_PATTERN.match(name):
        error = "שם התבנית חייב להכיל רק אותיות לועזיות קטנות, ספרות וקו תחתון (_)."
    elif category not in _CATEGORIES:
        error = "יש לבחור קטגוריה."
    elif not body_text:
        error = "יש למלא את תוכן ההודעה."
    else:
        placeholder_count = len(set(re.findall(r"\{\{(\d+)\}\}", body_text)))
        if placeholder_count and len(example_values) < placeholder_count:
            error = f"התבנית כוללת {placeholder_count} משתנים - צריך דוגמה לכל אחד מהם."

    if error:
        flash(error, "error")
        return redirect(url_for("whatsapp_templates.list_templates"))

    try:
        whatsapp_bot.create_message_template(
            config, name, category, "he", body_text,
            body_examples=example_values or None, footer_text=footer_text or None,
        )
    except Exception as exc:
        flash(f"יצירת התבנית נכשלה: {exc}", "error")
        return redirect(url_for("whatsapp_templates.list_templates"))

    flash(f"התבנית '{name}' נשלחה לאישור Meta (ממתינה - בדרך כלל דקות עד יום).", "success")
    return redirect(url_for("whatsapp_templates.list_templates"))

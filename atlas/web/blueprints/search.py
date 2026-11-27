import re

from flask import Blueprint, render_template, request, session

from atlas.core import roles
from atlas.core.auth import login_required
from atlas.data.context import get_repos
from atlas.web.blueprints.bot_conversations import _with_names, _with_number_labels

# חיפוש גלובלי מהסרגל העליון: לידים, לקוחות ושיחות בוט במכה אחת. הרשאות כמו בעמודים עצמם -
# לידים: מנהלת רואה הכול, אחרת רק מה ששויך אליה; שיחות בוט: למנהלת בלבד
bp = Blueprint("search", __name__, url_prefix="/search")

MAX_PER_GROUP = 15
MIN_QUERY_LENGTH = 2


def _digits(text):
    # 972501112233 / +972-50-111-2233 -> 0501112233, כך שמספר בפורמט בינלאומי מוצא מספר שמור בפורמט מקומי (ולהפך)
    digits = re.sub(r"\D", "", text or "")
    return "0" + digits[3:] if digits.startswith("972") and len(digits) >= 11 else digits


def _matches(query, digits, *fields):
    lowered = query.lower()
    for field in fields:
        value = str(field or "")
        if lowered in value.lower():
            return True
        if len(digits) >= 3 and digits in _digits(value):
            return True
    return False


@bp.route("/")
@login_required
def results():
    query = (request.args.get("q") or "").strip()
    digits = _digits(query)
    user = session.get("user") or {}
    is_admin = user.get("role") == roles.ADMIN
    leads, customers, chats = [], [], []

    if len(query) >= MIN_QUERY_LENGTH:
        repos = get_repos()

        lead_df = repos.leads.get_all()
        if not is_admin:
            lead_df = lead_df[lead_df["assigned_user"].fillna("") == user.get("username", "")]
        for record in lead_df.to_dict("records"):
            if _matches(query, digits, record.get("full_name"), record.get("phone")):
                leads.append(record)

        for record in repos.customers.get_all().to_dict("records"):
            if _matches(query, digits, record.get("name"), record.get("phone"), record.get("email")):
                customers.append(record)

        if is_admin:
            conversations = _with_names(
                _with_number_labels(repos.customer_bot_messages.get_conversation_summaries(), repos), repos
            )
            chats = [c for c in conversations if _matches(query, digits, c.get("full_name"), c["phone"], c.get("last_message_body"))]

    totals = {"leads": len(leads), "customers": len(customers), "chats": len(chats)}
    return render_template(
        "search/results.html", query=query, too_short=0 < len(query) < MIN_QUERY_LENGTH, totals=totals,
        leads=leads[:MAX_PER_GROUP], customers=customers[:MAX_PER_GROUP], chats=chats[:MAX_PER_GROUP],
        total_all=sum(totals.values()), is_admin=is_admin,
    )

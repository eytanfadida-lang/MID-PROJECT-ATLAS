import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from db_context import get_repos
from auth import login_required, admin_required, permission_required, PERMISSION_MANAGE_LEADS
from lead_input import CHANNELS
from lead_menu import LEAD_UPDATABLE_FIELDS, CONVERTED_STATUS
from appointment_input import BRANCHES
from view_utils import to_records

DEFAULT_STATUS_COLOR = "#95a5a6"

bp = Blueprint("leads", __name__, url_prefix="/leads")


@bp.route("/")
@login_required
def list_leads():
    status = request.args.get("status", "")
    phone = request.args.get("phone", "").strip()
    show_my_only = request.args.get("mine", "0") == "1"

    repos = get_repos()
    current_user = session.get("user")
    current_username = current_user.get("username") if current_user else ""

    if phone:
        df = repos.leads.get_by_phone(phone)
    elif status:
        df = repos.leads.get_by_status(status)
    else:
        df = repos.leads.get_all()

    if show_my_only and current_user and current_user.get("role") != "admin":
        df = df[df["assigned_user"].fillna("") == current_username]
    elif current_user and current_user.get("role") != "admin":
        df = df[df["assigned_user"].fillna("") == current_username]

    all_leads = repos.leads.get_all()
    all_phone_counts = all_leads["phone"].fillna("").astype(str).str.strip()
    duplicate_phones = set(
        all_phone_counts[all_phone_counts != ""].value_counts()[lambda series: series > 1].index
    )

    users = to_records(repos.users.get_all()) if hasattr(repos, "users") else []
    lead_records = to_records(df)
    for record in lead_records:
        phone_value = (record.get("phone") or "").strip()
        record["is_duplicate_phone"] = bool(phone_value and phone_value in duplicate_phones)

    return render_template(
        "leads/list.html",
        leads=lead_records,
        statuses=repos.lead_statuses.get_names(),
        status_colors=repos.lead_statuses.get_color_map(),
        default_status_color=DEFAULT_STATUS_COLOR,
        status=status,
        phone=phone,
        users=users,
        show_my_only=show_my_only,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_lead():
    if request.method == "POST":
        statuses = get_repos().lead_statuses.get_names()
        lead = {
            "full_name": request.form.get("full_name", ""),
            "phone": request.form.get("phone", ""),
            "status": statuses[0] if statuses else "",
            "channel": request.form.get("channel", CHANNELS[0]),
            "assigned_user": request.form.get("assigned_user", ""),
            "notes": request.form.get("notes", ""),
        }
        repos = get_repos()
        duplicate_exists = not repos.leads.get_by_phone(lead["phone"]).empty if lead.get("phone") else False
        lead_id = repos.leads.create(lead)
        if duplicate_exists:
            flash("נמצא מספר טלפון כפול – הליד נוצר עם סטטוס 'ליד כפול'.", "error")
        else:
            flash(f"Lead created successfully (id: {lead_id}).", "success")
        return redirect(url_for("leads.list_leads"))

    return render_template("leads/new.html", channels=CHANNELS)


@bp.route("/<int:lead_id>/edit", methods=["GET", "POST"])
@login_required
def edit(lead_id):
    repos = get_repos()
    current = repos.leads.get_by_id(lead_id)
    if current is None:
        flash("Lead not found.", "error")
        return redirect(url_for("leads.list_leads"))

    if request.method == "POST":
        for field_key, _ in LEAD_UPDATABLE_FIELDS:
            new_value = request.form.get(field_key, "")
            if new_value != (current.get(field_key) or ""):
                repos.leads.update_field(lead_id, field_key, new_value)

        assigned_user = request.form.get("assigned_user", "")
        if assigned_user != (current.get("assigned_user") or ""):
            repos.leads.update_field(lead_id, "assigned_user", assigned_user)

        flash("Lead updated successfully.", "success")
        return redirect(url_for("leads.list_leads"))

    users = to_records(repos.users.get_all()) if hasattr(repos, "users") else []
    statuses = repos.lead_statuses.get_names()
    return render_template("leads/edit.html", lead=current, statuses=statuses, channels=CHANNELS, users=users)


@bp.route("/<int:lead_id>/status", methods=["POST"])
@login_required
def update_status(lead_id):
    new_status = request.form.get("status", "")
    if new_status not in get_repos().lead_statuses.get_names():
        flash("Invalid status.", "error")
        return redirect(url_for("leads.list_leads"))

    get_repos().leads.update_field(lead_id, "status", new_status)
    flash("Lead status updated.", "success")
    return redirect(url_for("leads.list_leads"))


@bp.route("/statuses", methods=["GET", "POST"])
@permission_required(PERMISSION_MANAGE_LEADS)
def manage_statuses():
    repos = get_repos()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        color = request.form.get("color", DEFAULT_STATUS_COLOR)
        if not name:
            flash("יש להזין שם סטטוס.", "error")
        else:
            try:
                repos.lead_statuses.add(name, color)
                flash(f"הסטטוס '{name}' נוסף בהצלחה.", "success")
            except sqlite3.IntegrityError:
                flash(f"סטטוס בשם '{name}' כבר קיים.", "error")
        return redirect(url_for("leads.manage_statuses"))

    return render_template("leads/statuses.html", statuses=to_records(repos.lead_statuses.get_all()))


@bp.route("/statuses/<int:status_id>/color", methods=["POST"])
@permission_required(PERMISSION_MANAGE_LEADS)
def update_status_color(status_id):
    color = request.form.get("color", "")
    if color:
        get_repos().lead_statuses.update_color(status_id, color)
        flash("צבע הסטטוס עודכן.", "success")
    return redirect(url_for("leads.manage_statuses"))


@bp.route("/statuses/<int:status_id>/delete", methods=["POST"])
@permission_required(PERMISSION_MANAGE_LEADS)
def delete_status(status_id):
    if get_repos().lead_statuses.delete(status_id):
        flash("הסטטוס נמחק בהצלחה.", "success")
    else:
        flash("הסטטוס לא נמצא.", "error")
    return redirect(url_for("leads.manage_statuses"))


def _parse_lead_ids(form):
    return [int(value) for value in form.getlist("lead_ids") if value.strip().isdigit()]


@bp.route("/bulk/status", methods=["POST"])
@login_required
def bulk_update_status():
    lead_ids = _parse_lead_ids(request.form)
    new_status = request.form.get("status", "")
    repos = get_repos()

    if not lead_ids:
        flash("לא נבחרו לידים.", "error")
    elif new_status not in repos.lead_statuses.get_names():
        flash("Invalid status.", "error")
    else:
        repos.leads.bulk_update_status(lead_ids, new_status)
        flash(f"סטטוס עודכן עבור {len(lead_ids)} לידים.", "success")

    return redirect(url_for("leads.list_leads"))


@bp.route("/bulk/assign", methods=["POST"])
@login_required
def bulk_assign():
    lead_ids = _parse_lead_ids(request.form)
    assigned_user = request.form.get("assigned_user", "")

    if not lead_ids:
        flash("לא נבחרו לידים.", "error")
    else:
        get_repos().leads.bulk_assign(lead_ids, assigned_user)
        flash(f"{len(lead_ids)} לידים נותבו בהצלחה.", "success")

    return redirect(url_for("leads.list_leads"))


@bp.route("/bulk/delete", methods=["POST"])
@permission_required(PERMISSION_MANAGE_LEADS)
def bulk_delete():
    lead_ids = _parse_lead_ids(request.form)

    if not lead_ids:
        flash("לא נבחרו לידים.", "error")
    else:
        get_repos().leads.bulk_delete(lead_ids)
        flash(f"נמחקו {len(lead_ids)} לידים.", "success")

    return redirect(url_for("leads.list_leads"))


@bp.route("/<int:lead_id>/assign", methods=["POST"])
@login_required
def assign_lead(lead_id):
    repos = get_repos()
    assigned_user = request.form.get("assigned_user", "")
    lead = repos.leads.get_by_id(lead_id)
    if lead is None:
        flash("Lead not found.", "error")
        return redirect(url_for("leads.list_leads"))

    repos.leads.update_field(lead_id, "assigned_user", assigned_user)
    if assigned_user:
        flash(f"ליד '{lead.get('full_name', '')}' הוקצה ל-{assigned_user}.", "success")
    else:
        flash("הקצאת הליד בוטלה.", "success")
    return redirect(url_for("leads.list_leads"))


@bp.route("/<int:lead_id>/delete", methods=["POST"])
@permission_required(PERMISSION_MANAGE_LEADS)
def delete(lead_id):
    if get_repos().leads.delete(lead_id):
        flash("Lead deleted successfully.", "success")
    else:
        flash("Lead not found.", "error")
    return redirect(url_for("leads.list_leads"))


@bp.route("/<int:lead_id>/convert", methods=["GET", "POST"])
@login_required
def convert(lead_id):
    repos = get_repos()
    lead = repos.leads.get_by_id(lead_id)
    if lead is None:
        flash("Lead not found.", "error")
        return redirect(url_for("leads.list_leads"))

    if request.method == "POST":
        name_of_store = request.form.get("name_of_store", "")
        id_client = str(repos.id_sequence.next_id())
        repos.appointments.create_client(
            id_client=id_client,
            name_of_client=lead["full_name"],
            phone_client=lead["phone"],
            name_of_store=name_of_store,
        )
        repos.leads.update_field(lead_id, "status", CONVERTED_STATUS)
        flash(f"Lead converted to client successfully (client id: {id_client}).", "success")
        return redirect(url_for("leads.list_leads"))

    return render_template("leads/convert.html", lead=lead, branches=BRANCHES)

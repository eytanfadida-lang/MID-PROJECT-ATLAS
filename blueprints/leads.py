from flask import Blueprint, render_template, request, redirect, url_for, flash

from db_context import get_repos
from auth import login_required, admin_required
from lead_input import STATUSES, CHANNELS
from lead_menu import LEAD_UPDATABLE_FIELDS, CONVERTED_STATUS
from appointment_input import BRANCHES
from view_utils import to_records

bp = Blueprint("leads", __name__, url_prefix="/leads")


@bp.route("/")
@login_required
def list_leads():
    status = request.args.get("status", "")
    phone = request.args.get("phone", "").strip()

    repos = get_repos()
    if phone:
        df = repos.leads.get_by_phone(phone)
    elif status:
        df = repos.leads.get_by_status(status)
    else:
        df = repos.leads.get_all()

    return render_template(
        "leads/list.html",
        leads=to_records(df),
        statuses=STATUSES,
        status=status,
        phone=phone,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_lead():
    if request.method == "POST":
        lead = {
            "full_name": request.form.get("full_name", ""),
            "phone": request.form.get("phone", ""),
            "status": STATUSES[0],
            "channel": request.form.get("channel", CHANNELS[0]),
            "assigned_user": request.form.get("assigned_user", ""),
            "notes": request.form.get("notes", ""),
        }
        lead_id = get_repos().leads.create(lead)
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
        flash("Lead updated successfully.", "success")
        return redirect(url_for("leads.list_leads"))

    return render_template("leads/edit.html", lead=current, statuses=STATUSES, channels=CHANNELS)


@bp.route("/<int:lead_id>/status", methods=["POST"])
@login_required
def update_status(lead_id):
    new_status = request.form.get("status", "")
    if new_status not in STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("leads.list_leads"))

    get_repos().leads.update_field(lead_id, "status", new_status)
    flash("Lead status updated.", "success")
    return redirect(url_for("leads.list_leads"))


@bp.route("/<int:lead_id>/delete", methods=["POST"])
@admin_required
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

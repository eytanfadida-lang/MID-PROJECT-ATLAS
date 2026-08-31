import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash

from db_context import get_repos
from auth import login_required, admin_required, permission_required, PERMISSION_MANAGE_APPOINTMENTS
from settings import BRANCHES
from view_utils import to_records

bp = Blueprint("appointments", __name__, url_prefix="/appointments")


@bp.route("/")
@login_required
def list_appointments():
    phone = request.args.get("phone", "").strip()
    today_only = request.args.get("today") == "1"

    repos = get_repos()
    if phone:
        df = repos.appointments.get_by_phone(phone)
    elif today_only:
        df = repos.appointments.get_today()
    else:
        df = repos.appointments.get_all()

    return render_template(
        "appointments/list.html",
        appointments=to_records(df),
        phone=phone,
        today_only=today_only,
    )


@bp.route("/new")
@login_required
def new_choose_day():
    repos = get_repos()
    days = repos.availability.get_available_days()
    return render_template("appointments/new_day.html", days=days)


@bp.route("/new/hour")
@login_required
def new_choose_hour():
    date = request.args.get("date", "")
    repos = get_repos()
    hours = repos.availability.get_available_hours(date)
    return render_template("appointments/new_hour.html", date=date, hours=hours)


@bp.route("/new/details", methods=["GET", "POST"])
@login_required
def new_details():
    date = request.args.get("date", "")
    time = request.args.get("time", "")

    if request.method == "POST":
        repos = get_repos()
        appointment = {
            "id_client": str(repos.id_sequence.next_id()),
            "created_datetime_stamp": datetime.datetime.now(),
            "name_of_client": request.form.get("name_of_client", ""),
            "phone_client": request.form.get("phone_client", ""),
            "name_of_store": request.form.get("name_of_store", ""),
            "appointment_date": datetime.datetime.strptime(date, "%Y-%m-%d"),
            "appointment_time": datetime.datetime.strptime(time, "%H:%M"),
        }
        repos.appointments.create(appointment)
        flash(f"התור נוצר בהצלחה (מזהה: {appointment['id_client']}).", "success")
        return redirect(url_for("appointments.list_appointments"))

    return render_template("appointments/new_details.html", date=date, time=time, branches=BRANCHES)


@bp.route("/<id_client>/edit", methods=["GET", "POST"])
@login_required
def edit(id_client):
    repos = get_repos()
    current = repos.appointments.get_by_id(id_client)
    if current is None:
        flash("התור לא נמצא.", "error")
        return redirect(url_for("appointments.list_appointments"))

    if request.method == "POST":
        appointment_date_raw = request.form.get("appointment_date", "")
        appointment_time_raw = request.form.get("appointment_time", "")
        fields = {
            "name_of_client": request.form.get("name_of_client", ""),
            "phone_client": request.form.get("phone_client", ""),
            "name_of_store": request.form.get("name_of_store", ""),
            "appointment_date": (
                datetime.datetime.strptime(appointment_date_raw, "%Y-%m-%d") if appointment_date_raw else None
            ),
            "appointment_time": (
                datetime.datetime.strptime(appointment_time_raw, "%H:%M") if appointment_time_raw else None
            ),
        }
        repos.appointments.update(id_client, fields)
        flash("התור עודכן בהצלחה.", "success")
        return redirect(url_for("appointments.list_appointments"))

    return render_template("appointments/edit.html", appointment=current, branches=BRANCHES)


@bp.route("/<id_client>/delete", methods=["POST"])
@permission_required(PERMISSION_MANAGE_APPOINTMENTS)
def delete(id_client):
    repos = get_repos()
    if repos.appointments.delete(id_client):
        flash("התור נמחק בהצלחה.", "success")
    else:
        flash("התור לא נמצא.", "error")
    return redirect(url_for("appointments.list_appointments"))

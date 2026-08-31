from flask import Blueprint, render_template, request, redirect, url_for, flash

from db_context import get_repos
from auth import login_required, admin_required, permission_required, PERMISSION_MANAGE_CUSTOMERS
from settings import MEMBERSHIP_PLANS
from view_utils import to_records

bp = Blueprint("customers", __name__, url_prefix="/customers")


@bp.route("/")
@login_required
def list_customers():
    df = get_repos().customers.get_all()
    return render_template("customers/list.html", customers=to_records(df))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_customer():
    if request.method == "POST":
        repos = get_repos()
        customer = {
            "name": request.form.get("name", ""),
            "phone": request.form.get("phone", ""),
            "email": request.form.get("email", ""),
            "address": request.form.get("address", ""),
        }
        customer_id = repos.id_sequence.next_id()
        repos.customers.create(customer, customer_id)
        flash(f"הלקוח נוצר בהצלחה (מזהה: {customer_id}).", "success")
        return redirect(url_for("customers.list_customers"))

    return render_template("customers/new.html")


@bp.route("/<int:customer_id>")
@login_required
def detail(customer_id):
    repos = get_repos()
    customer = repos.customers.get_by_id(customer_id)
    if customer is None:
        flash("הלקוח לא נמצא.", "error")
        return redirect(url_for("customers.list_customers"))

    appointments = to_records(repos.appointments.get_by_customer_id(customer_id))
    invoices = to_records(repos.invoices.get_by_customer(customer_id))
    return render_template(
        "customers/detail.html",
        customer=customer,
        appointments=appointments,
        invoices=invoices,
        membership_plans=MEMBERSHIP_PLANS,
    )


@bp.route("/<int:customer_id>/invoices", methods=["POST"])
@login_required
def create_invoice(customer_id):
    repos = get_repos()
    if repos.customers.get_by_id(customer_id) is None:
        flash("הלקוח לא נמצא.", "error")
        return redirect(url_for("customers.list_customers"))

    try:
        amount = float(request.form.get("amount", ""))
    except ValueError:
        flash("סכום לא תקין.", "error")
        return redirect(url_for("customers.detail", customer_id=customer_id))

    invoice_number = repos.invoices.create(customer_id, amount)
    flash(f"החשבונית נוצרה בהצלחה (מספר חשבונית: {invoice_number}).", "success")
    return redirect(url_for("customers.detail", customer_id=customer_id))


@bp.route("/<int:customer_id>/membership", methods=["POST"])
@login_required
def purchase_membership(customer_id):
    repos = get_repos()
    if repos.customers.get_by_id(customer_id) is None:
        flash("הלקוח לא נמצא.", "error")
        return redirect(url_for("customers.list_customers"))

    plan_name = request.form.get("plan_name", "")
    plan = next((p for p in MEMBERSHIP_PLANS if p[0] == plan_name), None)
    if plan is None:
        flash("מסלול מנוי לא תקין.", "error")
        return redirect(url_for("customers.detail", customer_id=customer_id))

    name, price = plan
    invoice_number = repos.invoices.create(customer_id, price, name)
    flash(f"המנוי '{name}' נרכש בהצלחה (מספר חשבונית: {invoice_number}, סכום: {price}).", "success")
    return redirect(url_for("customers.detail", customer_id=customer_id))


@bp.route("/<int:customer_id>/link-appointment", methods=["POST"])
@login_required
def link_appointment(customer_id):
    repos = get_repos()
    if repos.customers.get_by_id(customer_id) is None:
        flash("הלקוח לא נמצא.", "error")
        return redirect(url_for("customers.list_customers"))

    id_client = request.form.get("id_client", "")
    if repos.appointments.get_by_id(id_client) is None:
        flash("התור לא נמצא.", "error")
        return redirect(url_for("customers.detail", customer_id=customer_id))

    repos.appointments.link_customer(id_client, customer_id)
    flash("התור קושר ללקוח בהצלחה.", "success")
    return redirect(url_for("customers.detail", customer_id=customer_id))


@bp.route("/<int:customer_id>/delete", methods=["POST"])
@permission_required(PERMISSION_MANAGE_CUSTOMERS)
def delete(customer_id):
    repos = get_repos()
    if repos.customers.get_by_id(customer_id) is None:
        flash("הלקוח לא נמצא.", "error")
        return redirect(url_for("customers.list_customers"))

    has_appointments = not repos.appointments.get_by_customer_id(customer_id).empty
    has_invoices = not repos.invoices.get_by_customer(customer_id).empty
    if has_appointments or has_invoices:
        flash("לא ניתן למחוק: ללקוח יש תורים או חשבוניות מקושרים.", "error")
        return redirect(url_for("customers.detail", customer_id=customer_id))

    repos.customers.delete(customer_id)
    flash("הלקוח נמחק בהצלחה.", "success")
    return redirect(url_for("customers.list_customers"))

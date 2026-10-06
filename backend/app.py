import os
import secrets
import sqlite3
from functools import wraps
from pathlib import Path
from datetime import date, datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request, session, send_from_directory
from sqlalchemy import func, inspect as sqlalchemy_inspect, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .extensions import db
from .models import Employee, Organization, User
from .validators import clean_text, date_value, email_value, employee_fields

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
load_dotenv(ROOT / ".env")


def create_app(test_config=None):
    # Keep Flask's root/instance paths stable both when imported and run with `python -m`.
    app = Flask("backend.app", static_folder=None, instance_path=str(ROOT / "instance"))
    production = os.getenv("APP_ENV", "development").lower() == "production"
    secret_key = os.getenv("SECRET_KEY")
    if production and not secret_key:
        raise RuntimeError("Set a private SECRET_KEY environment variable before starting in production.")
    database_url = os.getenv("DATABASE_URL", "sqlite:///employee_management.db")
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    app.config.update(
        SECRET_KEY=secret_key or "dev-only-change-me",
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production or os.getenv("COOKIE_SECURE", "0") == "1",
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    db.init_app(app)

    def response_error(message, status=400):
        return jsonify({"error": message}), status

    def current_user():
        user_id = session.get("user_id")
        return db.session.get(User, user_id) if user_id else None

    def require_auth(role=None):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                user = current_user()
                if not user:
                    return response_error("Please log in to continue.", 401)
                if role and user.role != role:
                    return response_error("You do not have permission to perform this action.", 403)
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    token = request.headers.get("X-CSRF-Token", "")
                    if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
                        return response_error("Your session token is missing or expired. Refresh and try again.", 400)
                return fn(user, *args, **kwargs)
            return wrapped
        return decorator

    def login_required(fn):
        return require_auth()(fn)

    def admin_required(fn):
        return require_auth("admin")(fn)

    def employee_required(fn):
        return require_auth("employee")(fn)

    @app.get("/api/csrf")
    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({"csrf_token": session["csrf_token"]})

    @app.post("/api/register")
    def register():
        return response_error("Employee accounts are created by an administrator.", 404)

    @app.get("/api/admin/setup-status")
    def admin_setup_status():
        organization = db.session.get(Organization, 1)
        has_admin = User.query.filter_by(role="admin").first() is not None
        return jsonify({
            "available": not has_admin and organization is None and bool(os.getenv("ADMIN_SETUP_KEY")),
            "company_name": organization.name if organization else "",
        })

    @app.post("/api/admin/register")
    def admin_register():
        token = request.headers.get("X-CSRF-Token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
            return response_error("Your session token is missing or expired. Refresh and try again.", 400)

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return response_error("Registration details must be a JSON object.")

        organization = db.session.get(Organization, 1)
        setup_mode = not User.query.filter_by(role="admin").first() and organization is None
        if not setup_mode:
            return response_error("Admin signup is managed by your company administrator. Ask them to add your account in Settings.", 403)
        try:
            company_name = clean_text(data.get("company_name"), "Company name", max_length=160)
            name = clean_text(data.get("name"), "Administrator name", max_length=120)
            email = email_value(data.get("email"))
            password = data.get("password", "")
            if not isinstance(password, str) or len(password) < 12 or len(password) > 128:
                return response_error("Password must be between 12 and 128 characters.")
            if password != data.get("confirm_password"):
                return response_error("Password confirmation does not match.")
            if User.query.filter_by(email=email).first():
                return response_error("That email address is already in use.", 409)

            setup_key = data.get("setup_key", "")
            expected_setup_key = os.getenv("ADMIN_SETUP_KEY", "")
            if not expected_setup_key or not isinstance(setup_key, str) or not secrets.compare_digest(setup_key, expected_setup_key):
                return response_error("A valid administrator setup key is required.", 403)
            organization = Organization(id=1, name=company_name)
            db.session.add(organization)

            admin = User(name=name, email=email, role="admin")
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            return response_error(str(exc))
        except IntegrityError:
            db.session.rollback()
            return response_error("Administrator registration could not be completed. Check the setup key and email, then retry.", 409)

        session.clear()
        session["user_id"] = admin.id
        session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({
            "message": "Company and administrator account created.",
            "company_name": organization.name,
            "user": {"id": admin.id, "full_name": admin.full_name, "email": admin.email, "role": admin.role},
            "csrf_token": session["csrf_token"],
        }), 201

    def authenticate(expected_role=None):
        token = request.headers.get("X-CSRF-Token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
            return response_error("Your session token is missing or expired. Refresh and try again.", 400)
        data = request.get_json(silent=True) or {}
        try:
            email = email_value(data.get("email"))
        except ValueError as exc:
            return response_error(str(exc))
        password = data.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not isinstance(password, str) or not user.check_password(password):
            return response_error("Email or password is incorrect.", 401)
        if user.role == "employee" and user.employee is None:
            return response_error("Your employee login is not linked to an employee record. Contact your administrator.", 403)
        if expected_role and user.role != expected_role:
            return response_error(f"This account cannot sign in through the {expected_role} login.", 403)
        session.clear()
        session["user_id"] = user.id
        session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({"message": "Welcome back.", "user": {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role}})

    @app.post("/api/login")
    def login():
        return authenticate()

    @app.post("/api/admin/login")
    def admin_login():
        return authenticate("admin")

    @app.post("/api/employee/login")
    def employee_login():
        return authenticate("employee")

    @app.post("/api/logout")
    @require_auth()
    def logout(_user):
        session.clear()
        return jsonify({"message": "Logged out."})

    @app.get("/api/me")
    def me():
        user = current_user()
        if not user:
            return response_error("Not logged in.", 401)
        return jsonify({"user": {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role}, "csrf_token": session.get("csrf_token")})

    @app.get("/api/dashboard")
    @admin_required
    def dashboard(_user):
        counts = {status: Employee.query.filter_by(employment_status=status).count() for status in ["Active", "On Leave", "Resigned", "Terminated"]}
        departments = db.session.query(Employee.department, func.count(Employee.id)).group_by(Employee.department).order_by(func.count(Employee.id).desc()).all()
        recent = Employee.query.order_by(Employee.created_at.desc()).limit(6).all()
        return jsonify({"total_employees": Employee.query.count(), "active_employees": counts["Active"], "on_leave_employees": counts["On Leave"], "resigned_employees": counts["Resigned"], "terminated_employees": counts["Terminated"], "department_count": len(departments), "departments": [{"name": name, "count": count} for name, count in departments], "statuses": [{"name": name, "count": count} for name, count in counts.items()], "recent_employees": [e.to_dict() for e in recent]})

    @app.get("/api/employees")
    @require_auth()
    def employees_list(user):
        if user.role != "admin":
            return response_error("You do not have permission to view the employee directory.", 403)
        query = Employee.query
        search = request.args.get("search", "").strip()
        department = request.args.get("department", "").strip()
        status = request.args.get("status", "").strip()
        if search:
            like = f"%{search}%"
            query = query.filter(or_(Employee.full_name.ilike(like), Employee.employee_code.ilike(like), Employee.email.ilike(like), Employee.designation.ilike(like)))
        if department:
            query = query.filter(Employee.department == department)
        if status:
            query = query.filter(Employee.employment_status == status)
        page = max(request.args.get("page", 1, type=int), 1)
        per_page = min(max(request.args.get("per_page", 10, type=int), 1), 100)
        pagination = query.order_by(Employee.full_name.asc()).paginate(page=page, per_page=per_page, error_out=False)
        departments = [row[0] for row in db.session.query(Employee.department).distinct().order_by(Employee.department).all()]
        return jsonify({"employees": [e.to_dict() for e in pagination.items], "page": pagination.page, "pages": pagination.pages, "total": pagination.total, "departments": departments})

    @app.get("/api/employees/<int:employee_id>")
    @require_auth()
    def employee_get(user, employee_id):
        employee = db.session.get(Employee, employee_id)
        if not employee:
            return response_error("Employee not found.", 404)
        if user.role != "admin" and employee.user_id != user.id:
            return response_error("You do not have permission to view this employee.", 403)
        return jsonify({"employee": employee.to_dict()})

    @app.get("/api/admin/employees/<int:employee_id>")
    @admin_required
    def admin_employee_get(_user, employee_id):
        employee = db.session.get(Employee, employee_id)
        if not employee:
            return response_error("Employee not found.", 404)
        return jsonify({"employee": employee.to_dict()})

    @app.post("/api/employees")
    @require_auth("admin")
    def employee_create(_user):
        data = request.get_json(silent=True) or {}
        try:
            fields = employee_fields(data)
            password = data.get("password", "")
            if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
                return response_error("A temporary password between 8 and 128 characters is required.")
            if Employee.query.filter_by(employee_code=fields["employee_code"]).first():
                return response_error("That employee code is already in use.", 409)
            if Employee.query.filter_by(email=fields["email"]).first():
                return response_error("That email is already in use.", 409)
            account = User.query.filter_by(email=fields["email"]).first()
            if account and (account.role != "employee" or account.employee):
                return response_error("That email is already linked to an employee record or is reserved for an administrator.", 409)
            if not account:
                account = User(name=fields["full_name"], email=fields["email"], role="employee")
                db.session.add(account)
            account.name = fields["full_name"]
            account.set_password(password)
            employee = Employee(**fields)
            employee.user = account
            db.session.add(employee)
            db.session.commit()
            return jsonify({"message": "Employee and login account created.", "employee": employee.to_dict()}), 201
        except ValueError as exc:
            db.session.rollback()
            return response_error(str(exc))
        except IntegrityError:
            db.session.rollback()
            return response_error("Employee code or email is already in use.", 409)

    @app.put("/api/employees/<int:employee_id>")
    @require_auth("admin")
    def employee_update(_user, employee_id):
        employee = db.session.get(Employee, employee_id)
        if not employee:
            return response_error("Employee not found.", 404)
        try:
            fields = employee_fields(request.get_json(silent=True) or {})
            code_owner = Employee.query.filter(Employee.employee_code == fields["employee_code"], Employee.id != employee_id).first()
            email_owner = Employee.query.filter(Employee.email == fields["email"], Employee.id != employee_id).first()
            linked_user = User.query.filter(User.email == fields["email"], User.id != employee.user_id if employee.user_id else True).first()
            if code_owner:
                return response_error("That employee code is already in use.", 409)
            if email_owner:
                return response_error("That email is already in use.", 409)
            if linked_user and (linked_user.role != "employee" or linked_user.employee):
                return response_error("That email is already linked to an employee record or is reserved for an administrator.", 409)
            password = (request.get_json(silent=True) or {}).get("password", "")
            account = employee.user or linked_user
            if not account and (not isinstance(password, str) or len(password) < 8 or len(password) > 128):
                return response_error("A temporary password between 8 and 128 characters is required to create this employee login.")
            for key, value in fields.items():
                setattr(employee, key, value)
            if not account:
                account = User(name=employee.full_name, email=employee.email, role="employee")
                db.session.add(account)
            account.name = employee.full_name
            account.email = employee.email
            if password:
                if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
                    return response_error("Password must be between 8 and 128 characters.")
                account.set_password(password)
            employee.user = account
            db.session.commit()
            return jsonify({"message": "Employee updated.", "employee": employee.to_dict()})
        except ValueError as exc:
            db.session.rollback()
            return response_error(str(exc))
        except IntegrityError:
            db.session.rollback()
            return response_error("Employee code or email is already in use.", 409)

    @app.delete("/api/employees/<int:employee_id>")
    @require_auth("admin")
    def employee_delete(_user, employee_id):
        employee = db.session.get(Employee, employee_id)
        if not employee:
            return response_error("Employee not found.", 404)
        if employee.user:
            db.session.delete(employee.user)
        db.session.delete(employee)
        db.session.commit()
        return jsonify({"message": "Employee deleted."})

    @app.get("/api/profile")
    @login_required
    def profile_get(user):
        if not user.employee:
            return response_error("No employee record is linked to this account. Contact your administrator.", 404)
        return jsonify({"employee": user.employee.to_dict()})

    @app.put("/api/profile")
    @employee_required
    def profile_update(user):
        if not user.employee:
            return response_error("No employee record is linked to this account. Contact your administrator.", 404)
        data = request.get_json(silent=True) or {}
        try:
            # Self-service fields are intentionally limited to contact and personal details.
            employee = user.employee
            employee.phone = clean_text(data.get("phone", employee.phone), "Phone", max_length=32)
            employee.address = clean_text(data.get("address", employee.address or ""), "Address", required=False, max_length=500)
            employee.gender = clean_text(data.get("gender", employee.gender or ""), "Gender", required=False, max_length=30)
            employee.date_of_birth = date_value(data.get("date_of_birth", employee.date_of_birth.isoformat() if employee.date_of_birth else ""), "Date of birth", required=False)
            password = data.get("new_password")
            if password:
                if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
                    return response_error("New password must be between 8 and 128 characters.")
                if not user.check_password(data.get("current_password", "")):
                    return response_error("Current password is incorrect.", 400)
                user.set_password(password)
            db.session.commit()
            return jsonify({"message": "Profile updated.", "employee": employee.to_dict()})
        except ValueError as exc:
            db.session.rollback()
            return response_error(str(exc))

    @app.get("/api/employee/dashboard")
    @employee_required
    def employee_dashboard(user):
        return jsonify({
            "user": {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role},
            "employee": user.employee.to_dict() if user.employee else None,
        })

    @app.get("/api/admin/accounts")
    @admin_required
    def admin_accounts(_user):
        accounts = User.query.filter_by(role="employee").order_by(User.full_name.asc()).all()
        return jsonify({"accounts": [{
            "id": account.id, "full_name": account.full_name, "email": account.email,
            "created_at": account.created_at.isoformat(), "employee_id": account.employee.id if account.employee else None,
        } for account in accounts]})

    @app.post("/api/admin/accounts/admin")
    @admin_required
    def admin_account_create(_user):
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return response_error("Administrator details must be a JSON object.")
        try:
            company_name = clean_text(data.get("company_name"), "Company name", max_length=160)
            name = clean_text(data.get("name"), "Administrator name", max_length=120)
            email = email_value(data.get("email"))
            password = data.get("password", "")
            if not isinstance(password, str) or len(password) < 12 or len(password) > 128:
                return response_error("Password must be between 12 and 128 characters.")
            if password != data.get("confirm_password"):
                return response_error("Password confirmation does not match.")
            if User.query.filter_by(email=email).first():
                return response_error("That email address is already in use.", 409)

            organization = db.session.get(Organization, 1)
            if organization is None:
                organization = Organization(id=1, name=company_name)
                db.session.add(organization)
            else:
                organization.name = company_name
            admin = User(name=name, email=email, role="admin")
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            return jsonify({
                "message": "Administrator account created.",
                "company_name": organization.name,
                "admin": {"id": admin.id, "full_name": admin.full_name, "email": admin.email, "role": admin.role},
            }), 201
        except ValueError as exc:
            db.session.rollback()
            return response_error(str(exc))
        except IntegrityError:
            db.session.rollback()
            return response_error("That email address is already in use.", 409)

    @app.put("/api/admin/account")
    @admin_required
    def admin_account_update(user):
        data = request.get_json(silent=True) or {}
        try:
            email = email_value(data.get("email"))
            current_password = data.get("current_password", "")
            if not isinstance(current_password, str) or not user.check_password(current_password):
                return response_error("Current password is incorrect.", 400)

            email_owner = User.query.filter(User.email == email, User.id != user.id).first()
            if email_owner:
                return response_error("That email address is already in use.", 409)

            new_password = data.get("new_password", "")
            if new_password:
                if not isinstance(new_password, str) or len(new_password) < 8 or len(new_password) > 128:
                    return response_error("New password must be between 8 and 128 characters.")
                user.set_password(new_password)

            user.email = email
            db.session.commit()
            session["csrf_token"] = secrets.token_urlsafe(32)
            return jsonify({
                "message": "Administrator login details updated.",
                "user": {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role},
                "csrf_token": session["csrf_token"],
            })
        except ValueError as exc:
            db.session.rollback()
            return response_error(str(exc))
        except IntegrityError:
            db.session.rollback()
            return response_error("That email address is already in use.", 409)

    # Keep the original API stable while exposing explicit, admin-scoped API URLs.
    app.add_url_rule("/api/admin/dashboard", endpoint="admin_dashboard_api", view_func=app.view_functions["dashboard"], methods=["GET"])
    app.add_url_rule("/api/admin/employees", endpoint="admin_employees_list_api", view_func=app.view_functions["employees_list"], methods=["GET"])
    app.add_url_rule("/api/admin/employees", endpoint="admin_employees_create_api", view_func=app.view_functions["employee_create"], methods=["POST"])
    app.add_url_rule("/api/admin/employees/<int:employee_id>", endpoint="admin_employee_update_api", view_func=app.view_functions["employee_update"], methods=["PUT", "PATCH"])
    app.add_url_rule("/api/admin/employees/<int:employee_id>", endpoint="admin_employee_delete_api", view_func=app.view_functions["employee_delete"], methods=["DELETE"])

    @app.errorhandler(413)
    def too_large(_error):
        return response_error("Request is too large.", 413)

    @app.errorhandler(SQLAlchemyError)
    def database_error(_error):
        db.session.rollback()
        app.logger.exception("Database operation failed")
        return response_error("A database error occurred. Please try again.", 500)

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/login")
    @app.get("/employee/login")
    def employee_login_page():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/register")
    def register_page():
        return response_error("Employee accounts are created by an administrator.", 404)

    @app.get("/admin/login")
    def admin_login_page():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/admin/dashboard")
    @admin_required
    def admin_dashboard_page(_user):
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/admin/employees")
    @admin_required
    def admin_employees_page(_user):
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/admin/employees/new")
    @admin_required
    def admin_employee_new_page(_user):
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/admin/employees/<int:employee_id>")
    @app.get("/admin/employees/<int:employee_id>/edit")
    @admin_required
    def admin_employee_page(_user, employee_id):
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/employee/dashboard")
    @employee_required
    def employee_dashboard_page(_user):
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/employee/profile")
    @employee_required
    def employee_profile_page(_user):
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/<path:path>")
    def frontend_file(path):
        if path.startswith("api/"):
            return response_error("API endpoint not found.", 404)
        target = (FRONTEND / path).resolve()
        if not str(target).startswith(str(FRONTEND.resolve())) or not target.is_file():
            return send_from_directory(FRONTEND, "index.html")
        return send_from_directory(FRONTEND, path)

    return app


def initialize_database(app_instance):
    """Create missing tables and safely migrate legacy user table/column names."""
    with app_instance.app_context():
        inspector = sqlalchemy_inspect(db.engine)
        tables = set(inspector.get_table_names())
        if "user" in tables and "users" not in tables:
            db.session.execute(text('ALTER TABLE "user" RENAME TO "users"'))
            db.session.commit()
            inspector = sqlalchemy_inspect(db.engine)
            tables = set(inspector.get_table_names())
        if "employee" in tables and "employees" not in tables:
            db.session.execute(text('ALTER TABLE "employee" RENAME TO "employees"'))
            db.session.commit()
            inspector = sqlalchemy_inspect(db.engine)
        if "users" in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns("users")}
            if "full_name" in columns and "name" not in columns:
                db.session.execute(text('ALTER TABLE "users" RENAME COLUMN "full_name" TO "name"'))
                db.session.commit()
        db.create_all()
        import_legacy_instance_data(app_instance)


def import_legacy_instance_data(app_instance):
    """Merge rows from the former backend/instance database without modifying it."""
    target = (Path(app_instance.instance_path) / "employee_management.db").resolve()
    database = db.engine.url.database
    configured_target = Path(database) if database else None
    if configured_target and not configured_target.is_absolute():
        configured_target = Path(app_instance.instance_path) / configured_target
    if configured_target is None or configured_target.resolve() != target:
        return
    legacy = (ROOT / "backend" / "instance" / "employee_management.db").resolve()
    if target == legacy or not legacy.is_file():
        return

    def parse_datetime(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    with sqlite3.connect(str(legacy)) as source:
        source.row_factory = sqlite3.Row
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        source_user_table = "users" if "users" in tables else "user" if "user" in tables else None
        source_employee_table = "employees" if "employees" in tables else "employee" if "employee" in tables else None
        legacy_users = source.execute(f'SELECT * FROM "{source_user_table}"').fetchall() if source_user_table else []
        legacy_employees = source.execute(f'SELECT * FROM "{source_employee_table}"').fetchall() if source_employee_table else []

    user_id_map = {}
    for row in legacy_users:
        values = dict(row)
        email = values.get("email", "").strip().lower()
        if not email:
            continue
        user = User.query.filter_by(email=email).first()
        if user is None:
            name = values.get("name") or values.get("full_name") or email
            role = values.get("role") if values.get("role") in {"admin", "employee"} else "employee"
            user = User(name=name, email=email, role=role, password_hash=values.get("password_hash") or "")
            created_at = parse_datetime(values.get("created_at"))
            if created_at:
                user.created_at = created_at
            db.session.add(user)
            db.session.flush()
        user_id_map[values.get("id")] = user.id

    for row in legacy_employees:
        values = dict(row)
        code, email = values.get("employee_code"), values.get("email", "").strip().lower()
        if not code or not email:
            continue
        employee = Employee.query.filter((Employee.employee_code == code) | (Employee.email == email)).first()
        linked_user_id = user_id_map.get(values.get("user_id"))
        account = db.session.get(User, linked_user_id) if linked_user_id else User.query.filter_by(email=email, role="employee").first()
        if employee is not None:
            if account and not employee.user_id and not account.employee and employee.email == account.email:
                employee.user = account
            continue
        joining_date = values.get("joining_date")
        birth_date = values.get("date_of_birth")
        employee = Employee(
            employee_code=code, full_name=values.get("full_name") or values.get("name") or email,
            email=email, phone=values.get("phone") or "", department=values.get("department") or "Unassigned",
            designation=values.get("designation") or "Employee", salary=values.get("salary") or 0,
            joining_date=date.fromisoformat(joining_date) if isinstance(joining_date, str) else joining_date or date.today(),
            gender=values.get("gender"), address=values.get("address"),
            date_of_birth=date.fromisoformat(birth_date) if isinstance(birth_date, str) and birth_date else birth_date,
            employment_status=values.get("employment_status") if values.get("employment_status") in {"Active", "On Leave", "Resigned", "Terminated"} else "Active",
        )
        created_at, updated_at = parse_datetime(values.get("created_at")), parse_datetime(values.get("updated_at"))
        if created_at:
            employee.created_at = created_at
        if updated_at:
            employee.updated_at = updated_at
        if account and not account.employee:
            employee.user = account
        db.session.add(employee)
    db.session.commit()

app = create_app()
initialize_database(app)


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")

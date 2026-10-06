import re
from datetime import date
from decimal import Decimal, InvalidOperation

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
STATUSES = {"Active", "On Leave", "Resigned", "Terminated"}


def clean_text(value, field, required=True, max_length=120):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} is required.")
    if len(value) > max_length:
        raise ValueError(f"{field} must be {max_length} characters or fewer.")
    return value or None


def email_value(value):
    value = clean_text(value, "Email", max_length=254).lower()
    if not EMAIL_RE.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    return value


def date_value(value, field, required=True):
    value = clean_text(value, field, required=required, max_length=10)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid date (YYYY-MM-DD).") from exc


def employee_fields(data):
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")
    fields = {
        "employee_code": clean_text(data.get("employee_code"), "Employee code", max_length=32).upper(),
        "full_name": clean_text(data.get("full_name"), "Full name", max_length=120),
        "email": email_value(data.get("email")),
        "phone": clean_text(data.get("phone"), "Phone", max_length=32),
        "department": clean_text(data.get("department"), "Department", max_length=80),
        "designation": clean_text(data.get("designation"), "Designation", max_length=100),
        "joining_date": date_value(data.get("joining_date"), "Joining date"),
        "gender": clean_text(data.get("gender"), "Gender", required=False, max_length=30),
        "address": clean_text(data.get("address"), "Address", required=False, max_length=500),
        "date_of_birth": date_value(data.get("date_of_birth"), "Date of birth", required=False),
        "employment_status": clean_text(data.get("employment_status"), "Employment status", max_length=20),
    }
    if fields["employment_status"] not in STATUSES:
        raise ValueError("Employment status must be Active, On Leave, Resigned, or Terminated.")
    try:
        salary = Decimal(str(data.get("salary", "")))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Salary must be a valid number.") from exc
    if not salary.is_finite() or salary < 0 or salary > Decimal("9999999999.99"):
        raise ValueError("Salary must be between 0 and 9,999,999,999.99.")
    fields["salary"] = salary.quantize(Decimal("0.01"))
    return fields

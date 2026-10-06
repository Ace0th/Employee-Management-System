"""Idempotently seed the initial administrator and 50 demo employees."""
import os
from datetime import date, timedelta

from .app import app, initialize_database
from .extensions import db
from .models import Employee, User

ADMIN_EMAIL = "admin@ace-limted.com"

EMPLOYEE_NAMES = [
    "Aarav Sharma", "Diya Patel", "Rohan Mehta", "Ananya Iyer", "Kabir Singh",
    "Meera Nair", "Arjun Rao", "Ishita Kapoor", "Vivaan Desai", "Sara Khan",
    "Aditya Menon", "Aisha Reddy", "Reyansh Shah", "Kavya Joshi", "Neil Thomas",
    "Tara Malhotra", "Dev Kulkarni", "Nisha Verma", "Karan Bhat", "Maya Das",
    "Siddharth Jain", "Leela Krishnan", "Ritvik Sinha", "Pooja Chawla", "Yash Gupta",
    "Rhea Fernandes", "Manav Pillai", "Sneha Mukherjee", "Omkar Patil", "Ira Bose",
    "Varun Shetty", "Tanvi Ghosh", "Akash Banerjee", "Priya Sethi", "Dhruv Anand",
    "Zoya Mirza", "Harsh Vora", "Neha Bansal", "Samar Khanna", "Aditi Kulkarni",
    "Nikhil Dutta", "Simran Kaur", "Parth Trivedi", "Mira Sen", "Kunal Arora",
    "Anika Menon", "Rahul Chatterjee", "Sana Qureshi", "Ishan Malhotra", "Lavanya Rao",
]
DEPARTMENTS = ["IT", "HR", "Finance", "Marketing", "Sales", "Operations"]
POSITIONS = {
    "IT": ["Software Engineer", "Systems Analyst", "QA Engineer", "IT Support Specialist", "Data Engineer"],
    "HR": ["HR Generalist", "Talent Acquisition Specialist", "People Operations Analyst", "HR Business Partner"],
    "Finance": ["Financial Analyst", "Accountant", "Payroll Specialist", "Finance Associate"],
    "Marketing": ["Marketing Coordinator", "Content Strategist", "Brand Manager", "Digital Marketing Analyst"],
    "Sales": ["Account Executive", "Sales Representative", "Sales Operations Analyst", "Customer Success Manager"],
    "Operations": ["Operations Coordinator", "Logistics Analyst", "Program Manager", "Business Operations Associate"],
}
STATUSES = ["Active"] * 8 + ["On Leave", "Resigned"]


def demo_employees():
    for index, name in enumerate(EMPLOYEE_NAMES, start=1):
        department = DEPARTMENTS[(index - 1) % len(DEPARTMENTS)]
        position = POSITIONS[department][((index - 1) // len(DEPARTMENTS)) % len(POSITIONS[department])]
        phone = f"+91 90000 {index:05d}"
        joined = date(2021, 1, 1) + timedelta(days=(index * 37) % 1900)
        yield {
            "employee_code": f"ACE{index:03d}",
            "full_name": name,
            "email": f"employee{index:03d}@ace-limted.com",
            "phone": phone,
            "department": department,
            "designation": position,
            "salary": 36000 + ((index * 1379) % 54000),
            "joining_date": joined,
            "employment_status": STATUSES[(index - 1) % len(STATUSES)],
        }


def seed(app_instance=None, *, admin_password=None, employee_password=None):
    app_instance = app_instance or app
    admin_password = admin_password or os.getenv("SEED_ADMIN_PASSWORD")
    employee_password = employee_password or os.getenv("SEED_EMPLOYEE_PASSWORD")
    with app_instance.app_context():
        initialize_database(app_instance)
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        if not admin and not admin_password:
            raise RuntimeError("Set SEED_ADMIN_PASSWORD to a private value before creating the initial admin.")
        if not employee_password:
            for fields in demo_employees():
                employee = Employee.query.filter(
                    (Employee.employee_code == fields["employee_code"]) | (Employee.email == fields["email"])
                ).first()
                account = User.query.filter_by(email=fields["email"]).first()
                if (employee is None and account is None) or (employee and not employee.user and account is None):
                    raise RuntimeError("Set SEED_EMPLOYEE_PASSWORD to a private value before creating demo employee logins.")
        if not admin:
            admin = User(name="Ace Limited Administrator", email=ADMIN_EMAIL, role="admin")
            admin.set_password(admin_password)
            db.session.add(admin)
        elif admin.role != "admin":
            raise RuntimeError(f"{ADMIN_EMAIL} is already used by a non-admin account; refusing to change its role.")

        for fields in demo_employees():
            employee = Employee.query.filter(
                (Employee.employee_code == fields["employee_code"]) | (Employee.email == fields["email"])
            ).first()
            if employee:
                # Preserve existing records and only repair their employee login if needed.
                if employee.employee_code == fields["employee_code"] and employee.email == fields["email"] and not employee.user:
                    account = User.query.filter_by(email=fields["email"]).first()
                    if not account:
                        account = User(name=employee.full_name, email=employee.email, role="employee")
                        account.set_password(employee_password)
                        db.session.add(account)
                    if account.role == "employee" and not account.employee:
                        employee.user = account
                continue

            account = User.query.filter_by(email=fields["email"]).first()
            if account and (account.role != "employee" or account.employee):
                # Never take over an existing admin or a login already linked elsewhere.
                continue
            if not account:
                account = User(name=fields["full_name"], email=fields["email"], role="employee")
                db.session.add(account)
            account.name = fields["full_name"]
            account.set_password(employee_password)
            employee = Employee(**fields, user=account)
            db.session.add(employee)

        db.session.commit()
        total = sum(1 for item in demo_employees() if Employee.query.filter_by(employee_code=item["employee_code"]).first())
        print(f"Database ready. Admin login: {ADMIN_EMAIL}")
        print(f"Demo employee records ready: {total}. No passwords were printed.")


if __name__ == "__main__":
    seed()

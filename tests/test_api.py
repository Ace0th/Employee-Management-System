"""Integration checks for authentication, permissions, and employee CRUD."""
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.app import create_app, initialize_database
from backend.extensions import db
from backend.models import Employee, Organization, User
from backend.seed import ADMIN_EMAIL, seed


EMPLOYEE = {
    "employee_code": "EMP-TEST", "full_name": "Test Person", "email": "test.person@example.com",
    "phone": "+1 555 0199", "department": "Engineering", "designation": "Developer",
    "salary": "75000", "joining_date": "2024-01-15", "employment_status": "Active",
    "gender": "Prefer not to say", "address": "10 Test Street", "date_of_birth": "1998-04-12",
    "password": "StartHere@2026",
}


class EmployeeApiFlows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True, "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + os.path.join(self.temp.name, "test.db").replace("\\", "/"),
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            admin = User(full_name="Admin User", email="admin@example.com", role="admin")
            admin.set_password("AdminPass123!")
            self.employee_user = User(full_name="Ava Patel", email="ava@example.com", role="employee")
            self.employee_user.set_password("EmployeePass123!")
            other_user = User(full_name="Other Person", email="other@example.com", role="employee")
            other_user.set_password("EmployeePass123!")
            db.session.add_all([admin, self.employee_user, other_user])
            db.session.flush()
            own = Employee(employee_code="EMP-001", full_name="Ava Patel", email="ava@example.com", phone="555-0100", department="Engineering", designation="Developer", salary=70000, joining_date=__import__('datetime').date(2023, 1, 1), employment_status="Active", user=self.employee_user)
            other = Employee(employee_code="EMP-002", full_name="Other Person", email="other@example.com", phone="555-0101", department="Design", designation="Designer", salary=65000, joining_date=__import__('datetime').date(2023, 2, 1), employment_status="On Leave", user=other_user)
            db.session.add_all([own, other])
            db.session.commit()
        self.csrf()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp.cleanup()

    def csrf(self):
        return self.client.get("/api/csrf").get_json()["csrf_token"]

    def write(self, method, path, **kwargs):
        kwargs.setdefault("headers", {})["X-CSRF-Token"] = self.csrf()
        return getattr(self.client, method)(path, **kwargs)

    def login(self, email, password):
        return self.write("post", "/api/login", json={"email": email, "password": password})

    def test_admin_dashboard_directory_and_employee_crud(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 401)
        self.assertEqual(self.login("admin@example.com", "wrong-password").status_code, 401)
        self.assertEqual(self.write("post", "/api/employee/login", json={"email": "admin@example.com", "password": "AdminPass123!"}).status_code, 403)
        admin_login = self.write("post", "/api/admin/login", json={"email": "admin@example.com", "password": "AdminPass123!"})
        self.assertEqual(admin_login.status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard").get_json()["total_employees"], 2)
        accounts = self.client.get("/api/admin/accounts").get_json()["accounts"]
        self.assertEqual(len(accounts), 2)
        self.assertNotIn("password_hash", accounts[0])
        admin_page = self.client.get("/admin/dashboard")
        self.assertEqual(admin_page.status_code, 200)
        admin_page.close()
        self.assertEqual(self.client.post("/api/employees", json=EMPLOYEE).status_code, 400)  # CSRF required
        created = self.write("post", "/api/admin/employees", json=EMPLOYEE)
        self.assertEqual(created.status_code, 201, created.get_json())
        employee_id = created.get_json()["employee"]["id"]
        self.assertEqual(self.write("post", "/api/employees", json=EMPLOYEE).status_code, 409)
        self.assertEqual(self.client.get("/api/employees?search=Test").get_json()["total"], 1)
        self.assertEqual(self.client.get("/api/employees?department=Engineering").get_json()["total"], 2)
        self.assertEqual(self.client.get(f"/api/employees/{employee_id}").status_code, 200)
        updated = dict(EMPLOYEE, designation="Senior Developer", salary="81000")
        self.assertEqual(self.write("put", f"/api/admin/employees/{employee_id}", json=updated).status_code, 200)
        self.assertEqual(self.client.get(f"/api/employees/{employee_id}").get_json()["employee"]["designation"], "Senior Developer")
        self.assertEqual(self.client.get("/api/employees/99999").status_code, 404)
        self.assertEqual(self.write("delete", f"/api/admin/employees/{employee_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/employees/{employee_id}").status_code, 404)

    def test_public_registration_is_disabled_and_admin_creates_login(self):
        payload = dict(EMPLOYEE, employee_code="EMP-NEW", full_name="New Employee", email="new@example.com")
        self.assertEqual(self.write("post", "/api/register", json=payload).status_code, 404)
        self.assertEqual(self.client.get("/register").status_code, 404)
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        with self.app.app_context():
            orphan = User(full_name="Unlinked Login", email="orphan@example.com", role="employee")
            orphan.set_password("OrphanPass123!")
            db.session.add(orphan)
            db.session.commit()
        self.assertEqual(self.write("post", "/api/employee/login", json={"email": "orphan@example.com", "password": "OrphanPass123!"}).status_code, 403)

        admin_client = self.app.test_client()
        token = admin_client.get("/api/csrf").get_json()["csrf_token"]
        login = admin_client.post("/api/admin/login", json={"email": "admin@example.com", "password": "AdminPass123!"}, headers={"X-CSRF-Token": token})
        self.assertEqual(login.status_code, 200)
        token = admin_client.get("/api/me").get_json()["csrf_token"]
        created = admin_client.post("/api/admin/employees", json=payload, headers={"X-CSRF-Token": token})
        self.assertEqual(created.status_code, 201, created.get_json())
        self.assertIsNotNone(created.get_json()["employee"]["user_id"])
        with self.app.app_context():
            account = User.query.filter_by(email="new@example.com").one()
            self.assertNotEqual(account.password_hash, payload["password"])
            self.assertTrue(account.check_password(payload["password"]))
            self.assertIn("name", {column["name"] for column in __import__('sqlalchemy').inspect(db.engine).get_columns("users")})
        employee_client = self.app.test_client()
        token = employee_client.get("/api/csrf").get_json()["csrf_token"]
        logged_in = employee_client.post("/api/employee/login", json={"email": "new@example.com", "password": payload["password"]}, headers={"X-CSRF-Token": token})
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(employee_client.get("/api/profile").status_code, 200)

    def test_employee_self_service_and_cross_account_denial(self):
        self.assertEqual(self.login("ava@example.com", "EmployeePass123!").status_code, 200)
        own = self.client.get("/api/profile").get_json()["employee"]
        self.assertEqual(own["employee_code"], "EMP-001")
        changed = self.write("put", "/api/profile", json={"phone": "555-7777", "address": "New address"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.get_json()["employee"]["phone"], "555-7777")
        employee_page = self.client.get("/employee/dashboard")
        self.assertEqual(employee_page.status_code, 200)
        employee_page.close()
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/accounts").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/employees/1").status_code, 403)
        self.assertEqual(self.client.get("/api/employees/1").status_code, 200)
        self.assertEqual(self.client.get("/api/employees/2").status_code, 403)
        self.assertEqual(self.client.get("/api/employees").status_code, 403)
        self.assertEqual(self.write("put", "/api/employees/2", json=EMPLOYEE).status_code, 403)
        self.assertEqual(self.write("delete", "/api/employees/2").status_code, 403)
        self.assertEqual(self.write("post", "/api/admin/employees", json=EMPLOYEE).status_code, 403)
        self.assertEqual(self.write("delete", "/api/admin/employees/2").status_code, 403)
        self.assertEqual(self.write("post", "/api/register", json={"role": "admin"}).status_code, 404)
        changed_password = self.write("put", "/api/profile", json={"current_password": "EmployeePass123!", "new_password": "ChangedPass123!"})
        self.assertEqual(changed_password.status_code, 200)
        self.assertEqual(self.write("post", "/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.login("ava@example.com", "ChangedPass123!").status_code, 200)


class FirstAdminSetup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True, "SECRET_KEY": "first-admin-test",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + os.path.join(self.temp.name, "first-admin.db").replace("\\", "/"),
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp.cleanup()

    def write(self, path, payload):
        token = self.client.get("/api/csrf").get_json()["csrf_token"]
        return self.client.post(path, json=payload, headers={"X-CSRF-Token": token})

    def test_public_admin_signup_is_available_without_a_setup_key(self):
        payload = {
            "name": "First Admin", "email": "first.admin@example.com",
            "password": "Admin123", "confirm_password": "Admin123",
        }
        with patch.dict(os.environ, {"ADMIN_SETUP_KEY": ""}):
            self.assertTrue(self.client.get("/api/admin/setup-status").get_json()["available"])
            too_short = self.write("/api/admin/register", dict(payload, email="short.admin@example.com", password="Admin12", confirm_password="Admin12"))
            self.assertEqual(too_short.status_code, 400)
            created = self.write("/api/admin/register", payload)
            self.assertEqual(created.status_code, 201, created.get_json())
            self.assertEqual(created.get_json()["user"]["role"], "admin")
            setup_status = self.client.get("/api/admin/setup-status").get_json()
            self.assertTrue(setup_status["available"])
            self.assertTrue(setup_status["has_admin"])
            second = self.write("/api/admin/register", dict(payload, email="another.admin@example.com"))
            self.assertEqual(second.status_code, 201, second.get_json())
            self.assertEqual(second.get_json()["user"]["role"], "admin")
        with self.app.app_context():
            admin = User.query.filter_by(email=payload["email"]).one()
            self.assertNotEqual(admin.password_hash, payload["password"])
            self.assertTrue(admin.check_password(payload["password"]))

    def test_first_admin_can_be_created_when_workspace_already_exists(self):
        with self.app.app_context():
            db.session.add(Organization(id=1, name="PeopleOS Portfolio"))
            db.session.commit()
        payload = {
            "name": "Workspace Admin", "email": "workspace.admin@example.com",
            "password": "WorkspacePass123!", "confirm_password": "WorkspacePass123!",
        }
        response = self.write("/api/admin/register", payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["company_name"], "PeopleOS Portfolio")

    def test_public_admin_signup_can_be_disabled_by_configuration(self):
        payload = {
            "name": "Blocked Admin", "email": "blocked.admin@example.com",
            "password": "BlockedAdminPass123!", "confirm_password": "BlockedAdminPass123!",
        }
        with patch.dict(os.environ, {"PUBLIC_ADMIN_SIGNUP": "0"}):
            self.assertFalse(self.client.get("/api/admin/setup-status").get_json()["available"])
            response = self.write("/api/admin/register", payload)
            self.assertEqual(response.status_code, 403)


class LegacyDatabaseMigration(unittest.TestCase):
    def test_old_user_table_and_names_are_preserved_when_migrated(self):
        legacy_app = create_app({
            "TESTING": True, "SECRET_KEY": "migration-test",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        })
        with legacy_app.app_context():
            db.session.execute(__import__('sqlalchemy').text("CREATE TABLE user (id INTEGER PRIMARY KEY, full_name VARCHAR(120) NOT NULL, email VARCHAR(254) NOT NULL UNIQUE, password_hash VARCHAR(256) NOT NULL, role VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL)"))
            db.session.execute(__import__('sqlalchemy').text("INSERT INTO user VALUES (7, 'Legacy Admin', 'legacy@example.com', 'hash-value', 'admin', CURRENT_TIMESTAMP)"))
            db.session.commit()
        initialize_database(legacy_app)
        with legacy_app.app_context():
            account = db.session.get(User, 7)
            self.assertEqual(account.name, "Legacy Admin")
            self.assertEqual(account.full_name, "Legacy Admin")
            self.assertIn("users", __import__('sqlalchemy').inspect(db.engine).get_table_names())
            db.session.remove()
            db.engine.dispose()


class DemoSeed(unittest.TestCase):
    def test_seed_adds_50_unique_accounts_once_and_hashes_passwords(self):
        temp = tempfile.TemporaryDirectory()
        app = create_app({
            "TESTING": True, "SECRET_KEY": "seed-test",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + os.path.join(temp.name, "seed.db").replace("\\", "/"),
        })
        try:
            seed(app, admin_password="TestSeedAdmin@123", employee_password="TestSeedEmployee@123")
            seed(app, admin_password="TestSeedAdmin@123", employee_password="TestSeedEmployee@123")
            with app.app_context():
                employees = Employee.query.filter(Employee.employee_code.like("ACE%"))
                self.assertEqual(employees.count(), 50)
                self.assertEqual(Employee.query.filter(Employee.email.like("employee%@peopleos.example")).count(), 50)
                self.assertEqual(employees.count(), Employee.query.filter(Employee.employee_code.like("ACE%"), Employee.user_id.isnot(None)).count())
                admin = User.query.filter_by(email=ADMIN_EMAIL).one()
                self.assertEqual(admin.role, "admin")
                self.assertTrue(admin.check_password("TestSeedAdmin@123"))
                employee = User.query.filter_by(email="employee001@peopleos.example").one()
                self.assertTrue(employee.check_password("TestSeedEmployee@123"))
                self.assertNotEqual(employee.password_hash, "TestSeedEmployee@123")
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()

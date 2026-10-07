# Employee Management System

A full-stack employee management app with a Flask API, SQLAlchemy, a relational database, and a responsive JavaScript frontend.

## Features

- Separate employee and admin login flows and dashboards.
- Server-enforced role checks on admin and employee endpoints, CSRF protection on writes, and Werkzeug password hashes.
- Admins can search, view, add, edit, and delete employees. Creating an employee also creates their employee login.
- Public administrator signup is available from the Admin Login page; every signup receives full admin access.
- Employees can see only their own linked employee information and edit permitted profile details.
- Public employee registration is disabled. Admins issue employee credentials.

## Run locally

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m backend.create_admin
python -m backend.app
```

Open <http://127.0.0.1:5000/employee/login> or <http://127.0.0.1:5000/admin/login>. The default database is `instance/employee_management.db`. Set a private `SECRET_KEY` in `.env` before using the app beyond local development.

Open `/admin/login` and select **Create First Admin Account** (the link changes to **Create Admin Account** after the first signup). Admin signup is public by default, and every successful signup receives full administrator privileges. Set `PUBLIC_ADMIN_SIGNUP=0` to disable public signups and restrict new admin accounts to signed-in administrators. Alternatively, create the initial local admin with `python -m backend.create_admin`.

## Production deployment

This app can run as a Render Web Service or a Vercel Flask Function. For either hosted deployment, provision managed PostgreSQL and configure:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT backend.app:app`
- Environment: `APP_ENV=production`, `FLASK_DEBUG=0`, `COOKIE_SECURE=1`, `SECRET_KEY` as a generated secret, and `DATABASE_URL` as the managed PostgreSQL connection string.

For Vercel, import the repository root as the project root and set those environment variables for Production and Preview. `pyproject.toml` points Vercel to `backend.app:app`, and `vercel.json` bundles the frontend files with the function. If `DATABASE_URL` is absent on Vercel, the app uses `/tmp/peopleos-preview.db` only to avoid a startup crash; that file is ephemeral and is not suitable for user or employee data. A persistent PostgreSQL `DATABASE_URL` is required for a usable deployment. Set a stable private `SECRET_KEY`; production startup intentionally fails when it is missing.

The app creates its tables at startup. Create an administrator by registering at `/admin/register` or run `python -m backend.create_admin` in a secure shell with production environment variables set. Public admin registration grants full employee-data access to anyone who completes signup; set `PUBLIC_ADMIN_SIGNUP=0` before using the deployment as a real company system. Passwords are stored as hashes. Do not run the demo seed on a real employee database. Use a managed database and backups; the local SQLite file is for development.

## Demo data

The optional seed creates employee records `ACE001`–`ACE050` across IT, HR, Finance, Marketing, Sales, and Operations. Existing data is retained, and repeated seeding does not duplicate these employee records. The seed has no built-in passwords: set `SEED_ADMIN_PASSWORD` and `SEED_EMPLOYEE_PASSWORD` privately when initializing a fresh demo database, then run `python -m backend.seed`. Do not set these in a production service unless you intentionally want the demo records there. Re-running the seed does not reset existing account passwords. Normal app startup does not seed demo accounts.

## Database and security

`users` stores name, unique email, hashed password, role (`admin` or `employee`), and creation time. `organization_settings` stores the single-company workspace name. `employees` stores employee IDs and employment/contact information with a unique optional user link. Existing SQLite data is preserved by the local in-place schema migration. Subsequent admin account creation requires an authenticated administrator.

Do not commit `.env`, database files, local password notes, or real employee information. Only use fictional records in public screenshots and portfolio demos.

## Tests

Run `python -m unittest discover -s tests -v` for authentication, role enforcement, CRUD, password hashing, registration denial, legacy migration, and seed idempotency checks.

## Main routes

- Employee login: `/employee/login`
- Employee dashboard: `/employee/dashboard`
- Admin login: `/admin/login`
- Admin dashboard: `/admin/dashboard`
- Admin employee API: `/api/admin/employees`
- Employee self-service API: `/api/profile`

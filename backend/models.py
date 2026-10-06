from datetime import date, datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import CheckConstraint
from sqlalchemy.orm import synonym
from sqlalchemy.orm import validates

from .extensions import db


class Organization(db.Model):
    __tablename__ = "organization_settings"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class AdminInvite(db.Model):
    __tablename__ = "admin_invites"

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True))


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'employee')", name="ck_user_role"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    full_name = synonym("name")
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="employee")
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    employee = db.relationship("Employee", back_populates="user", uselist=False, cascade="all, delete-orphan")

    @validates("role")
    def validate_role(self, _key, value):
        if value not in {"admin", "employee"}:
            raise ValueError("Role must be admin or employee.")
        return value

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    employee_code = db.Column(db.String(32), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(32), nullable=False)
    department = db.Column(db.String(80), nullable=False, index=True)
    designation = db.Column(db.String(100), nullable=False)
    salary = db.Column(db.Numeric(12, 2), nullable=False)
    joining_date = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(30))
    address = db.Column(db.String(500))
    date_of_birth = db.Column(db.Date)
    employment_status = db.Column(db.String(20), nullable=False, default="Active", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    user = db.relationship("User", back_populates="employee")

    def to_dict(self):
        return {
            "id": self.id, "employee_code": self.employee_code, "full_name": self.full_name,
            "email": self.email, "phone": self.phone, "department": self.department,
            "designation": self.designation, "salary": float(self.salary),
            "joining_date": self.joining_date.isoformat(), "gender": self.gender,
            "address": self.address, "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "employment_status": self.employment_status,
            "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(),
            "user_id": self.user_id,
        }

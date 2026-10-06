"""Create an administrator from a local terminal without a public signup route."""
from getpass import getpass

from .app import app, initialize_database
from .extensions import db
from .models import User
from .validators import clean_text, email_value


def main():
    initialize_database(app)
    with app.app_context():
        name = clean_text(input("Administrator name: "), "Name", max_length=120)
        email = email_value(input("Administrator email: "))
        if User.query.filter_by(email=email).first():
            raise SystemExit("That email already belongs to an account.")
        password = getpass("Password (12 characters minimum): ")
        if len(password) < 12 or len(password) > 128:
            raise SystemExit("Password must be between 12 and 128 characters.")
        if password != getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        user = User(name=name, email=email, role="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Administrator account created for {email}.")


if __name__ == "__main__":
    main()

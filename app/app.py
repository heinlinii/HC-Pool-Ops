    import os
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder="templates", static_folder="static")

app.secret_key = os.environ.get("SECRET_KEY", "poolops-dev-secret")

database_url = os.environ.get("DATABASE_URL", "")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///poolops.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    notes = db.Column(db.Text)

    properties = db.relationship(
        "Property",
        backref="client",
        lazy=True,
        cascade="all, delete-orphan",
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Property(db.Model):
    __tablename__ = "properties"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)

    property_name = db.Column(db.String(150))
    street = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    pool_type = db.Column(db.String(100))
    cover_type = db.Column(db.String(100))
    notes = db.Column(db.Text)


def login_required(route_function):
    @wraps(route_function)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)

    return wrapped


@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session["user_id"] = user.id
            session["username"] = user.username
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/create-admin")
def create_admin():
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "password123")

    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        return f"Admin user '{username}' already exists."

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return f"Admin user '{username}' created successfully."


@app.route("/dashboard")
@login_required
def dashboard():
    client_count = Client.query.count()
    property_count = Property.query.count()
    recent_clients = Client.query.order_by(Client.id.desc()).limit(5).all()
    recent_properties = Property.query.order_by(Property.id.desc()).limit(5).all()

    return render_template(
        "dashboard.html",
        username=session.get("username", "User"),
        client_count=client_count,
        property_count=property_count,
        recent_clients=recent_clients,
        recent_properties=recent_properties,
    )


@app.route("/clients")
@login_required
def clients():
    all_clients = Client.query.order_by(Client.last_name.asc(), Client.first_name.asc()).all()
    return render_template("clients.html", clients=all_clients)


@app.route("/clients/add", methods=["GET", "POST"])
@login_required
def add_client():
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        notes = request.form.get("notes", "").strip()

        if not first_name or not last_name:
            flash("First name and last name are required.", "error")
            return redirect(url_for("add_client"))

        new_client = Client(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            notes=notes,
        )
        db.session.add(new_client)
        db.session.commit()

        flash("Client added successfully.", "success")
        return redirect(url_for("clients"))

    return render_template("add_client.html")


@app.route("/properties")
@login_required
def properties():
    all_properties = Property.query.order_by(Property.id.desc()).all()
    return render_template("properties.html", properties=all_properties)


@app.route("/properties/add", methods=["GET", "POST"])
@login_required
def add_property():
    all_clients = Client.query.order_by(Client.last_name.asc(), Client.first_name.asc()).all()

    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        property_name = request.form.get("property_name", "").strip()
        street = request.form.get("street", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        zip_code = request.form.get("zip_code", "").strip()
        pool_type = request.form.get("pool_type", "").strip()
        cover_type = request.form.get("cover_type", "").strip()
        notes = request.form.get("notes", "").strip()

        if not client_id or not street:
            flash("Client and street are required.", "error")
            return redirect(url_for("add_property"))

        new_property = Property(
            client_id=int(client_id),
            property_name=property_name,
            street=street,
            city=city,
            state=state,
            zip_code=zip_code,
            pool_type=pool_type,
            cover_type=cover_type,
            notes=notes,
        )
        db.session.add(new_property)
        db.session.commit()

        flash("Property added successfully.", "success")
        return redirect(url_for("properties"))

    return render_template("add_property.html", clients=all_clients)


@app.route("/schedule")
@login_required
def schedule():
    return render_template("schedule.html")


@app.route("/schedule/new")
@login_required
def schedule_new():
    return render_template("schedule_new.html")


@app.route("/today")
@login_required
def today():
    return render_template("today.html")


@app.route("/users")
@login_required
def users():
    return render_template("users.html")


@app.route("/employees")
@login_required
def employees():
    return render_template("employees.html")


@app.route("/employees/new")
@login_required
def employee_new():
    return render_template("employee_new.html")


@app.route("/field")
@login_required
def field_dashboard():
    return render_template("field_dashboard.html")


@app.route("/office")
@login_required
def office_dashboard():
    return render_template("office_dashboard.html")


@app.route("/search")
@login_required
def search():
    return render_template("search.html")


@app.route("/requests")
@login_required
def requests_page():
    return render_template("requests.html")


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
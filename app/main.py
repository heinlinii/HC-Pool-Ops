import os
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

database_url = os.environ.get("DATABASE_URL", "")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

if not database_url:
    database_url = "sqlite:///poolops.db"

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# -------------------------
# Models
# -------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    properties = db.relationship("Property", backref="client", lazy=True, cascade="all, delete-orphan")


class Property(db.Model):
    __tablename__ = "properties"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(120), nullable=True)
    state = db.Column(db.String(50), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    jobs = db.relationship("Job", backref="property", lazy=True, cascade="all, delete-orphan")


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="Open")
    description = db.Column(db.Text, nullable=True)

@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    # TEMP dummy data (so page loads without breaking)
    jobs = [
        {
            "id": 1,
            "client_name": "Smith",
            "property_name": "Backyard Pool",
            "date": "2026-04-21",
            "status": "Scheduled"
        }
    ]

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "jobs": jobs
    })
# -------------------------
# Helpers
# -------------------------
def login_required(route_function):
    @wraps(route_function)
    def wrapped_route(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)
    return wrapped_route


# -------------------------
# Startup
# -------------------------
with app.app_context():
    db.create_all()

    existing_user = User.query.filter_by(username="admin").first()
    if not existing_user:
        admin = User(username="admin")
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()
        print("Created default login: admin / admin123")


# -------------------------
# Auth Routes
# -------------------------
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
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# Main Pages
# -------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    client_count = Client.query.count()
    property_count = Property.query.count()
    job_count = Job.query.count()
    open_jobs = Job.query.filter(Job.status != "Completed").count()

    recent_clients = Client.query.order_by(Client.id.desc()).limit(5).all()
    recent_jobs = Job.query.order_by(Job.id.desc()).limit(5).all()

    return render_template(
        "dashboard.html",
        current_user=session.get("username"),
        client_count=client_count,
        property_count=property_count,
        job_count=job_count,
        open_jobs=open_jobs,
        recent_clients=recent_clients,
        recent_jobs=recent_jobs,
    )


# -------------------------
# Clients
# -------------------------
@app.route("/clients", methods=["GET", "POST"])
@login_required
def clients():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        notes = request.form.get("notes", "").strip()

        if not name:
            flash("Client name is required.", "error")
            return redirect(url_for("clients"))

        new_client = Client(
            name=name,
            phone=phone,
            email=email,
            notes=notes
        )
        db.session.add(new_client)
        db.session.commit()
        flash("Client added successfully.", "success")
        return redirect(url_for("clients"))

    all_clients = Client.query.order_by(Client.name.asc()).all()
    return render_template("clients.html", clients=all_clients)


# -------------------------
# Properties
# -------------------------
@app.route("/properties", methods=["GET", "POST"])
@login_required
def properties():
    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        name = request.form.get("name", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        zip_code = request.form.get("zip_code", "").strip()
        notes = request.form.get("notes", "").strip()

        if not client_id or not name:
            flash("Property name and client are required.", "error")
            return redirect(url_for("properties"))

        new_property = Property(
            client_id=int(client_id),
            name=name,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            notes=notes
        )
        db.session.add(new_property)
        db.session.commit()
        flash("Property added successfully.", "success")
        return redirect(url_for("properties"))

    all_properties = Property.query.order_by(Property.id.desc()).all()
    all_clients = Client.query.order_by(Client.name.asc()).all()
    return render_template("properties.html", properties=all_properties, clients=all_clients)


# -------------------------
# Jobs
# -------------------------
@app.route("/jobs", methods=["GET", "POST"])
@login_required
def jobs():
    if request.method == "POST":
        property_id = request.form.get("property_id", "").strip()
        title = request.form.get("title", "").strip()
        status = request.form.get("status", "Open").strip()
        description = request.form.get("description", "").strip()

        if not property_id or not title:
            flash("Job title and property are required.", "error")
            return redirect(url_for("jobs"))

        new_job = Job(
            property_id=int(property_id),
            title=title,
            status=status,
            description=description
        )
        db.session.add(new_job)
        db.session.commit()
        flash("Job added successfully.", "success")
        return redirect(url_for("jobs"))

    all_jobs = Job.query.order_by(Job.id.desc()).all()
    all_properties = Property.query.order_by(Property.id.desc()).all()
    return render_template("jobs.html", jobs=all_jobs, properties=all_properties)


# -------------------------
# Error Handlers
# -------------------------
@app.errorhandler(404)
def not_found(_error):
    return render_template("base.html", page_title="Not Found", content_only="""
        <div class="card narrow-card">
            <h1>404</h1>
            <p>That page does not exist.</p>
            <a class="btn" href="/dashboard">Back to Dashboard</a>
        </div>
    """), 404


@app.errorhandler(500)
def internal_error(_error):
    db.session.rollback()
    return """
    <html>
        <head>
            <title>Server Error</title>
            <style>
                body { font-family: Arial, sans-serif; padding: 40px; background: #f4f7fb; }
                .box { max-width: 700px; margin: 0 auto; background: white; padding: 30px; border-radius: 14px; box-shadow: 0 8px 25px rgba(0,0,0,.08); }
                a { color: #0b5ed7; }
            </style>
        </head>
        <body>
            <div class="box">
                <h1>Internal Server Error</h1>
                <p>Something went wrong on the server.</p>
                <p><a href="/dashboard">Back to Dashboard</a></p>
                <p><a href="/logout">Log Out</a></p>
            </div>
        </body>
    </html>
    """, 500


if __name__ == "__main__":
    app.run(debug=True)
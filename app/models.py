from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from datetime import datetime
from app.database import Base


class Employee(Base):
    __tablename__ = "poolops2_employees"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    phone = Column(String, default="")
    email = Column(String, default="")
    active = Column(Boolean, default=True)


class Client(Base):
    __tablename__ = "poolops2_clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, default="")
    email = Column(String, default="")
    notes = Column(Text, default="")


class Property(Base):
    __tablename__ = "poolops2_properties"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=True)
    client = Column(String, nullable=False)
    address = Column(String, nullable=False)
    pool_type = Column(String, default="")
    notes = Column(Text, default="")


class Job(Base):
    __tablename__ = "poolops2_jobs"

    id = Column(Integer, primary_key=True, index=True)
    client = Column(String, nullable=False)
    property = Column(String, default="")
    address = Column(String, default="")
    job_type = Column(String, default="")
    status = Column(String, default="Pending")
    crew = Column(String, default="Unassigned")
    date = Column(String, default="")
    priority = Column(String, default="Normal")
    notes = Column(Text, default="")


class Invoice(Base):
    __tablename__ = "poolops2_invoices"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, nullable=True)
    client = Column(String, nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Float, default=0)
    status = Column(String, default="Draft")
    date = Column(String, default="")
    notes = Column(Text, default="")


class JobCost(Base):
    __tablename__ = "poolops2_job_costs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, nullable=True)
    client = Column(String, nullable=False)
    labor = Column(Float, default=0)
    materials = Column(Float, default=0)
    subs = Column(Float, default=0)
    equipment = Column(Float, default=0)
    fuel = Column(Float, default=0)
    other = Column(Float, default=0)
    invoice_amount = Column(Float, default=0)
    notes = Column(Text, default="")


class PhotoLog(Base):
    __tablename__ = "poolops2_photo_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, nullable=True)
    client = Column(String, nullable=False)
    photo_type = Column(String, default="Progress")
    title = Column(String, nullable=False)
    photo_url = Column(String, default="/static/logo.png")
    date = Column(String, default="")
    notes = Column(Text, default="")


class User(Base):
    __tablename__ = "poolops2_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, default="crew")
    name = Column(String, nullable=False)
    # =========================================
# PHASE 11 — DAILY FIELD LOGS
# =========================================

class FieldLog(Base):
    __tablename__ = "field_logs"

    id = Column(Integer, primary_key=True, index=True)

    employee_name = Column(String, default="")
    crew = Column(String, default="")

    client = Column(String, default="")
    property = Column(String, default="")
    address = Column(String, default="")

    date = Column(String, default="")

    arrival_time = Column(String, default="")
    departure_time = Column(String, default="")

    total_hours = Column(Float, default=0)

    truck = Column(String, default="")
    trailer = Column(String, default="")

    tools_used = Column(Text, default="")
    materials_used = Column(Text, default="")
    equipment_used = Column(Text, default="")

    fuel_cost = Column(Float, default=0)

    work_completed = Column(Text, default="")
    issues = Column(Text, default="")
    next_steps = Column(Text, default="")

    weather = Column(String, default="")

    photo_count = Column(Integer, default=0)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )
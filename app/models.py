from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text
from sqlalchemy.orm import relationship
from .database import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(50), default="")
    email = Column(String(255), default="")
    billing_address = Column(String(255), default="")
    notes = Column(Text, default="")

    properties = relationship("Property", back_populates="client", cascade="all, delete-orphan")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    role = Column(String(100), default="")
    phone = Column(String(50), default="")
    email = Column(String(255), default="")
    status = Column(String(50), default="active")
    notes = Column(Text, default="")

    schedule_items = relationship("ScheduleItem", back_populates="employee")
    users = relationship("User", back_populates="employee")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="field")  # admin / office / field
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)

    employee = relationship("Employee", back_populates="users")


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    address = Column(String(255), nullable=False)
    city = Column(String(100), default="")
    state = Column(String(50), default="")
    zip_code = Column(String(20), default="")
    pool_type = Column(String(100), default="")
    cover_type = Column(String(100), default="")
    gate_code = Column(String(100), default="")
    install_year = Column(String(20), default="")
    notes = Column(Text, default="")
    estimate_status = Column(String(50), default="none")

    client = relationship("Client", back_populates="properties")
    service_stops = relationship("ServiceStop", back_populates="property", cascade="all, delete-orphan")
    schedule_items = relationship("ScheduleItem", back_populates="property", cascade="all, delete-orphan")
    client_requests = relationship("ClientRequest", back_populates="property", cascade="all, delete-orphan")


class ServiceStop(Base):
    __tablename__ = "service_stops"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    date = Column(String(50), default="")
    tech_name = Column(String(255), default="")
    status = Column(String(50), default="completed")
    problem_reported = Column(Text, default="")
    work_performed = Column(Text, default="")
    recommendation = Column(Text, default="")
    labor_hours = Column(Float, default=0)
    labor_rate = Column(Float, default=0)
    material_cost = Column(Float, default=0)
    trip_charge = Column(Float, default=0)
    tax = Column(Float, default=0)
    billed_amount = Column(Float, default=0)
    paid_status = Column(String(50), default="unpaid")
    invoice_notes = Column(Text, default="")
    photo_path = Column(String(255), default="")

    property = relationship("Property", back_populates="service_stops")


class ScheduleItem(Base):
    __tablename__ = "schedule_items"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    date = Column(String(50), default="")
    start_time = Column(String(20), default="")
    end_time = Column(String(20), default="")
    assigned_to = Column(String(255), default="")
    job_type = Column(String(100), default="")
    status = Column(String(50), default="scheduled")
    priority = Column(String(50), default="normal")
    notes = Column(Text, default="")

    property = relationship("Property", back_populates="schedule_items")
    employee = relationship("Employee", back_populates="schedule_items")


class ClientRequest(Base):
    __tablename__ = "client_requests"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    client_name = Column(String(255), nullable=False)
    phone = Column(String(50), default="")
    email = Column(String(255), default="")
    address = Column(String(255), default="")
    request_type = Column(String(100), default="")
    description = Column(Text, default="")
    status = Column(String(50), default="new")

    property = relationship("Property", back_populates="client_requests")
from extensions import db
from datetime import datetime


class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    employees = db.relationship('Employee', backref='department', lazy=True,
                                foreign_keys='Employee.department_id')

    def __repr__(self):
        return f'<Department {self.name}>'


class Employee(db.Model):
    __tablename__ = 'employees'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    job_title = db.Column(db.String(100))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    hire_date = db.Column(db.Date, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    manager = db.relationship('Employee', remote_side=[id], backref='subordinates')
    time_entries = db.relationship('TimeEntry', backref='employee', lazy=True)

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    @property
    def is_clocked_in(self):
        open_entry = TimeEntry.query.filter_by(
            employee_id=self.id, clock_out=None
        ).first()
        return open_entry is not None

    @property
    def active_entry(self):
        return TimeEntry.query.filter_by(
            employee_id=self.id, clock_out=None
        ).first()

    def __repr__(self):
        return f'<Employee {self.full_name}>'


class TimeEntry(db.Model):
    __tablename__ = 'time_entries'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    clock_out = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.String(255))

    @property
    def duration_hours(self):
        if self.clock_out:
            delta = self.clock_out - self.clock_in
            return round(delta.total_seconds() / 3600, 2)
        return None

    def __repr__(self):
        return f'<TimeEntry {self.employee_id} {self.clock_in}>'

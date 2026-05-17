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


class EmploymentAgreement(db.Model):
    __tablename__ = 'employment_agreements'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    pay_type = db.Column(db.String(20), nullable=False)  # hourly | daily | monthly | shift

    # Hourly & Shift
    min_hours_per_day = db.Column(db.Float, nullable=True)   # None = no minimum
    min_hours_per_week = db.Column(db.Float, nullable=True)

    # Daily
    min_days_per_week = db.Column(db.Integer, nullable=True)

    # Monthly — fixed schedule
    work_start_time = db.Column(db.Time, nullable=True)   # e.g. 09:00
    work_end_time = db.Column(db.Time, nullable=True)     # e.g. 17:00
    break_minutes = db.Column(db.Integer, default=0)

    # Monthly — flexible
    is_flexible = db.Column(db.Boolean, default=False)
    flexible_daily_hours = db.Column(db.Float, nullable=True)  # e.g. 8.0

    employees = db.relationship('Employee', backref='agreement', lazy=True)
    shift_templates = db.relationship('ShiftTemplate', backref='agreement',
                                      lazy=True, cascade='all, delete-orphan')

    @property
    def pay_type_label(self):
        return {'hourly': 'Hourly', 'daily': 'Daily',
                'monthly': 'Monthly', 'shift': 'Shift'}.get(self.pay_type, self.pay_type)

    @property
    def schedule_summary(self):
        if self.pay_type == 'monthly':
            if self.is_flexible:
                return f'Flexible — {self.flexible_daily_hours or "?"} hrs/day'
            if self.work_start_time and self.work_end_time:
                s = self.work_start_time.strftime('%H:%M')
                e = self.work_end_time.strftime('%H:%M')
                brk = f', {self.break_minutes} min break' if self.break_minutes else ''
                return f'Fixed {s}–{e}{brk}'
        if self.pay_type in ('hourly', 'shift'):
            parts = []
            if self.min_hours_per_day:
                parts.append(f'Min {self.min_hours_per_day} hrs/day')
            if self.min_hours_per_week:
                parts.append(f'Min {self.min_hours_per_week} hrs/week')
            return ', '.join(parts) or 'No minimum'
        if self.pay_type == 'daily':
            if self.min_days_per_week:
                return f'Min {self.min_days_per_week} days/week'
            return 'No minimum'
        return ''

    def __repr__(self):
        return f'<EmploymentAgreement {self.name}>'


class ShiftTemplate(db.Model):
    __tablename__ = 'shift_templates'
    id = db.Column(db.Integer, primary_key=True)
    agreement_id = db.Column(db.Integer, db.ForeignKey('employment_agreements.id'),
                             nullable=False)
    name = db.Column(db.String(50), nullable=False)   # e.g. Morning, Evening, Night
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    @property
    def label(self):
        return f'{self.name} ({self.start_time.strftime("%H:%M")}–{self.end_time.strftime("%H:%M")})'

    def __repr__(self):
        return f'<ShiftTemplate {self.name}>'


class PublicHoliday(db.Model):
    __tablename__ = 'public_holidays'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    is_recurring = db.Column(db.Boolean, default=False)  # repeat every year same M/D
    notes = db.Column(db.String(255))

    def __repr__(self):
        return f'<PublicHoliday {self.name} {self.date}>'


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
    agreement_id = db.Column(db.Integer, db.ForeignKey('employment_agreements.id'),
                             nullable=True)
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
        return TimeEntry.query.filter_by(employee_id=self.id, clock_out=None).first() is not None

    @property
    def active_entry(self):
        return TimeEntry.query.filter_by(employee_id=self.id, clock_out=None).first()

    def __repr__(self):
        return f'<Employee {self.full_name}>'


class TimeEntry(db.Model):
    __tablename__ = 'time_entries'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    clock_out = db.Column(db.DateTime, nullable=True)
    shift_template_id = db.Column(db.Integer, db.ForeignKey('shift_templates.id'),
                                  nullable=True)
    notes = db.Column(db.String(255))

    shift_template = db.relationship('ShiftTemplate', backref='time_entries')

    @property
    def duration_hours(self):
        if self.clock_out:
            delta = self.clock_out - self.clock_in
            return round(delta.total_seconds() / 3600, 2)
        return None

    def __repr__(self):
        return f'<TimeEntry {self.employee_id} {self.clock_in}>'

from flask import Flask, render_template, request, redirect, url_for, flash
from extensions import db
from models import Department, Employee, TimeEntry, EmploymentAgreement, ShiftTemplate, PublicHoliday
from datetime import datetime, date, time as time_type
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'timekeeping-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///timekeeping.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_holiday_dates():
    today = date.today()
    holidays = PublicHoliday.query.all()
    dates = set()
    for h in holidays:
        if h.is_recurring:
            for yr in [today.year - 1, today.year, today.year + 1]:
                try:
                    dates.add(date(yr, h.date.month, h.date.day))
                except ValueError:
                    pass
        else:
            dates.add(h.date)
    return dates


def enrich_entries(entries, holiday_dates):
    result = []
    for entry in entries:
        info = {
            'entry': entry,
            'is_holiday': entry.clock_in.date() in holiday_dates,
            'late_minutes': None,
            'overtime_hours': None,
            'short_hours': None,
            'expected_hours': None,
        }
        agr = entry.employee.agreement if entry.employee else None
        if agr and agr.pay_type == 'monthly' and entry.clock_out:
            if agr.is_flexible and agr.flexible_daily_hours:
                info['expected_hours'] = agr.flexible_daily_hours
                diff = round(agr.flexible_daily_hours - (entry.duration_hours or 0), 2)
                info['short_hours'] = diff if diff > 0 else 0
                info['overtime_hours'] = abs(diff) if diff < 0 else 0
            elif not agr.is_flexible and agr.work_start_time and agr.work_end_time:
                ref_date = entry.clock_in.date()
                scheduled_start = datetime.combine(ref_date, agr.work_start_time)
                scheduled_end = datetime.combine(ref_date, agr.work_end_time)
                expected_secs = (scheduled_end - scheduled_start).total_seconds() - (agr.break_minutes * 60)
                info['expected_hours'] = round(expected_secs / 3600, 2)
                late_secs = (entry.clock_in.replace(second=0, microsecond=0) - scheduled_start).total_seconds()
                info['late_minutes'] = max(0, int(late_secs / 60))
                clock_out_clean = entry.clock_out.replace(second=0, microsecond=0)
                over_secs = (clock_out_clean - scheduled_end).total_seconds()
                info['overtime_hours'] = max(0, round(over_secs / 3600, 2))
        result.append(info)
    return result


def parse_time(s):
    if not s:
        return None
    h, m = map(int, s.split(':'))
    return time_type(h, m)


# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    total_employees = Employee.query.filter_by(is_active=True).count()
    total_departments = Department.query.count()
    clocked_in = TimeEntry.query.filter_by(clock_out=None).count()
    recent_entries = TimeEntry.query.order_by(TimeEntry.clock_in.desc()).limit(10).all()
    holiday_dates = get_holiday_dates()
    today_is_holiday = date.today() in holiday_dates
    today_holiday = None
    if today_is_holiday:
        for h in PublicHoliday.query.all():
            check = date.today()
            hdate = h.date
            if h.is_recurring:
                hdate = date(check.year, h.date.month, h.date.day)
            if hdate == check:
                today_holiday = h
                break
    return render_template('dashboard.html',
                           total_employees=total_employees,
                           total_departments=total_departments,
                           clocked_in=clocked_in,
                           recent_entries=recent_entries,
                           today_holiday=today_holiday)


# ─── Departments ─────────────────────────────────────────────────────────────

@app.route('/departments')
def departments():
    depts = Department.query.order_by(Department.name).all()
    return render_template('departments/index.html', departments=depts)


@app.route('/departments/add', methods=['GET', 'POST'])
def add_department():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        if not name:
            flash('Department name is required.', 'danger')
            return render_template('departments/form.html', action='Add', dept=None)
        if Department.query.filter_by(name=name).first():
            flash('A department with that name already exists.', 'danger')
            return render_template('departments/form.html', action='Add', dept=None)
        dept = Department(name=name, description=description)
        db.session.add(dept)
        db.session.commit()
        flash(f'Department "{name}" created successfully.', 'success')
        return redirect(url_for('departments'))
    return render_template('departments/form.html', action='Add', dept=None)


@app.route('/departments/<int:dept_id>/edit', methods=['GET', 'POST'])
def edit_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        if not name:
            flash('Department name is required.', 'danger')
            return render_template('departments/form.html', action='Edit', dept=dept)
        existing = Department.query.filter_by(name=name).first()
        if existing and existing.id != dept_id:
            flash('A department with that name already exists.', 'danger')
            return render_template('departments/form.html', action='Edit', dept=dept)
        dept.name = name
        dept.description = description
        db.session.commit()
        flash(f'Department "{name}" updated successfully.', 'success')
        return redirect(url_for('departments'))
    return render_template('departments/form.html', action='Edit', dept=dept)


@app.route('/departments/<int:dept_id>/delete', methods=['POST'])
def delete_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    if dept.employees:
        flash('Cannot delete department with assigned employees.', 'danger')
        return redirect(url_for('departments'))
    db.session.delete(dept)
    db.session.commit()
    flash('Department deleted.', 'success')
    return redirect(url_for('departments'))


# ─── Employment Agreements ────────────────────────────────────────────────────

@app.route('/agreements')
def agreements():
    agrs = EmploymentAgreement.query.order_by(EmploymentAgreement.name).all()
    return render_template('agreements/index.html', agreements=agrs)


def _save_agreement(agr):
    agr.name = request.form.get('name', '').strip()
    agr.description = request.form.get('description', '').strip()
    agr.pay_type = request.form.get('pay_type', 'monthly')

    # Hourly / Shift
    agr.min_hours_per_day = float(v) if (v := request.form.get('min_hours_per_day', '').strip()) else None
    agr.min_hours_per_week = float(v) if (v := request.form.get('min_hours_per_week', '').strip()) else None

    # Daily
    agr.min_days_per_week = int(v) if (v := request.form.get('min_days_per_week', '').strip()) else None

    # Monthly
    agr.is_flexible = 'is_flexible' in request.form
    agr.flexible_daily_hours = float(v) if (v := request.form.get('flexible_daily_hours', '').strip()) else None
    agr.work_start_time = parse_time(request.form.get('work_start_time', '').strip())
    agr.work_end_time = parse_time(request.form.get('work_end_time', '').strip())
    bm = request.form.get('break_minutes', '0').strip()
    agr.break_minutes = int(bm) if bm else 0


@app.route('/agreements/add', methods=['GET', 'POST'])
def add_agreement():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Agreement name is required.', 'danger')
            return render_template('agreements/form.html', action='Add', agr=None)
        if EmploymentAgreement.query.filter_by(name=name).first():
            flash('An agreement with that name already exists.', 'danger')
            return render_template('agreements/form.html', action='Add', agr=None)

        agr = EmploymentAgreement()
        _save_agreement(agr)
        db.session.add(agr)
        db.session.flush()

        if agr.pay_type == 'shift':
            _save_shift_templates(agr)

        db.session.commit()
        flash(f'Agreement "{agr.name}" created.', 'success')
        return redirect(url_for('agreements'))
    return render_template('agreements/form.html', action='Add', agr=None)


@app.route('/agreements/<int:agr_id>/edit', methods=['GET', 'POST'])
def edit_agreement(agr_id):
    agr = EmploymentAgreement.query.get_or_404(agr_id)
    if request.method == 'POST':
        _save_agreement(agr)
        # Replace shift templates
        for st in agr.shift_templates:
            db.session.delete(st)
        db.session.flush()
        if agr.pay_type == 'shift':
            _save_shift_templates(agr)
        db.session.commit()
        flash(f'Agreement "{agr.name}" updated.', 'success')
        return redirect(url_for('agreements'))
    return render_template('agreements/form.html', action='Edit', agr=agr)


def _save_shift_templates(agr):
    names = request.form.getlist('shift_name')
    starts = request.form.getlist('shift_start')
    ends = request.form.getlist('shift_end')
    for i, sname in enumerate(names):
        sname = sname.strip()
        if sname and i < len(starts) and i < len(ends):
            st = ShiftTemplate(
                agreement_id=agr.id,
                name=sname,
                start_time=parse_time(starts[i]),
                end_time=parse_time(ends[i]),
            )
            db.session.add(st)


@app.route('/agreements/<int:agr_id>/delete', methods=['POST'])
def delete_agreement(agr_id):
    agr = EmploymentAgreement.query.get_or_404(agr_id)
    if agr.employees:
        flash('Cannot delete an agreement that has employees assigned to it.', 'danger')
        return redirect(url_for('agreements'))
    db.session.delete(agr)
    db.session.commit()
    flash('Agreement deleted.', 'success')
    return redirect(url_for('agreements'))


# ─── Public Holidays ──────────────────────────────────────────────────────────

@app.route('/holidays')
def holidays():
    h_list = PublicHoliday.query.order_by(PublicHoliday.date).all()
    return render_template('holidays/index.html', holidays=h_list)


@app.route('/holidays/add', methods=['GET', 'POST'])
def add_holiday():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        date_str = request.form.get('date', '').strip()
        is_recurring = 'is_recurring' in request.form
        notes = request.form.get('notes', '').strip()
        if not name or not date_str:
            flash('Name and date are required.', 'danger')
            return render_template('holidays/form.html', action='Add', holiday=None)
        h = PublicHoliday(name=name, date=date.fromisoformat(date_str),
                          is_recurring=is_recurring, notes=notes)
        db.session.add(h)
        db.session.commit()
        flash(f'Holiday "{name}" added.', 'success')
        return redirect(url_for('holidays'))
    return render_template('holidays/form.html', action='Add', holiday=None)


@app.route('/holidays/<int:hid>/edit', methods=['GET', 'POST'])
def edit_holiday(hid):
    h = PublicHoliday.query.get_or_404(hid)
    if request.method == 'POST':
        h.name = request.form.get('name', '').strip()
        date_str = request.form.get('date', '').strip()
        h.date = date.fromisoformat(date_str) if date_str else h.date
        h.is_recurring = 'is_recurring' in request.form
        h.notes = request.form.get('notes', '').strip()
        db.session.commit()
        flash(f'Holiday "{h.name}" updated.', 'success')
        return redirect(url_for('holidays'))
    return render_template('holidays/form.html', action='Edit', holiday=h)


@app.route('/holidays/<int:hid>/delete', methods=['POST'])
def delete_holiday(hid):
    h = PublicHoliday.query.get_or_404(hid)
    db.session.delete(h)
    db.session.commit()
    flash('Holiday deleted.', 'success')
    return redirect(url_for('holidays'))


GHANA_HOLIDAYS = [
    # Fixed recurring — same date every year
    {'name': "New Year's Day",    'month': 1,  'day': 1,  'recurring': True,  'notes': 'Ghana statutory holiday'},
    {'name': "Constitution Day",  'month': 1,  'day': 7,  'recurring': True,  'notes': 'Ghana statutory holiday'},
    {'name': "Independence Day",  'month': 3,  'day': 6,  'recurring': True,  'notes': 'Ghana statutory holiday'},
    {'name': "Labour Day",        'month': 5,  'day': 1,  'recurring': True,  'notes': 'Ghana statutory holiday'},
    {'name': "Republic Day",      'month': 7,  'day': 1,  'recurring': True,  'notes': 'Ghana statutory holiday'},
    {'name': "Founder's Day",     'month': 9,  'day': 21, 'recurring': True,  'notes': 'Ghana statutory holiday'},
    {'name': "Christmas Day",     'month': 12, 'day': 25, 'recurring': True,  'notes': 'Ghana statutory holiday'},
    {'name': "Boxing Day",        'month': 12, 'day': 26, 'recurring': True,  'notes': 'Ghana statutory holiday'},
    # Movable — 2026 specific dates
    {'name': "Good Friday",       'month': 4,  'day': 3,  'recurring': False, 'notes': '2026 date — update annually'},
    {'name': "Easter Monday",     'month': 4,  'day': 6,  'recurring': False, 'notes': '2026 date — update annually'},
    {'name': "Farmer's Day",      'month': 12, 'day': 4,  'recurring': False, 'notes': '2026 date (first Friday of Dec) — update annually'},
    {'name': "Eid-Ul-Fitr",       'month': 3,  'day': 31, 'recurring': False, 'notes': '2026 approx. date — confirm with Office of Chief Imam'},
    {'name': "Shaqq Day",         'month': 4,  'day': 1,  'recurring': False, 'notes': '2026 approx. date (day after Eid-Ul-Fitr)'},
    {'name': "Eid-Ul-Adha",       'month': 6,  'day': 6,  'recurring': False, 'notes': '2026 approx. date — confirm with Office of Chief Imam'},
]


@app.route('/holidays/seed-ghana', methods=['POST'])
def seed_ghana_holidays():
    added = 0
    skipped = 0
    year = date.today().year
    for h in GHANA_HOLIDAYS:
        d = date(year, h['month'], h['day'])
        existing = PublicHoliday.query.filter_by(name=h['name']).first()
        if existing:
            skipped += 1
            continue
        entry = PublicHoliday(name=h['name'], date=d,
                              is_recurring=h['recurring'], notes=h['notes'])
        db.session.add(entry)
        added += 1
    db.session.commit()
    flash(f'Ghana holidays loaded: {added} added, {skipped} already existed.', 'success')
    return redirect(url_for('holidays'))
    flash('Holiday deleted.', 'success')
    return redirect(url_for('holidays'))


# ─── Employees ───────────────────────────────────────────────────────────────

@app.route('/employees')
def employees():
    dept_filter = request.args.get('department', '')
    search = request.args.get('search', '')
    query = Employee.query
    if dept_filter:
        query = query.filter_by(department_id=dept_filter)
    if search:
        query = query.filter(
            (Employee.first_name.ilike(f'%{search}%')) |
            (Employee.last_name.ilike(f'%{search}%')) |
            (Employee.email.ilike(f'%{search}%'))
        )
    emps = query.order_by(Employee.last_name, Employee.first_name).all()
    depts = Department.query.order_by(Department.name).all()
    return render_template('employees/index.html', employees=emps,
                           departments=depts, dept_filter=dept_filter, search=search)


@app.route('/employees/add', methods=['GET', 'POST'])
def add_employee():
    departments = Department.query.order_by(Department.name).all()
    managers = Employee.query.filter_by(is_active=True).order_by(Employee.last_name).all()
    agrs = EmploymentAgreement.query.order_by(EmploymentAgreement.name).all()
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        errors = []
        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')
        if not email:
            errors.append('Email is required.')
        elif Employee.query.filter_by(email=email).first():
            errors.append('An employee with that email already exists.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('employees/form.html', action='Add', emp=None,
                                   departments=departments, managers=managers, agreements=agrs)
        hire_date_str = request.form.get('hire_date', '')
        hire_date = date.fromisoformat(hire_date_str) if hire_date_str else date.today()
        emp = Employee(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=request.form.get('phone', '').strip(),
            job_title=request.form.get('job_title', '').strip(),
            department_id=request.form.get('department_id') or None,
            manager_id=request.form.get('manager_id') or None,
            agreement_id=request.form.get('agreement_id') or None,
            hire_date=hire_date,
        )
        db.session.add(emp)
        db.session.commit()
        flash(f'Employee {emp.full_name} added successfully.', 'success')
        return redirect(url_for('employees'))
    return render_template('employees/form.html', action='Add', emp=None,
                           departments=departments, managers=managers, agreements=agrs)


@app.route('/employees/<int:emp_id>')
def view_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    entries = (TimeEntry.query.filter_by(employee_id=emp_id)
               .order_by(TimeEntry.clock_in.desc()).limit(20).all())
    total_hours = sum(e.duration_hours for e in entries if e.duration_hours)
    holiday_dates = get_holiday_dates()
    enriched = enrich_entries(entries, holiday_dates)
    return render_template('employees/view.html', emp=emp, enriched=enriched,
                           total_hours=round(total_hours, 2))


@app.route('/employees/<int:emp_id>/edit', methods=['GET', 'POST'])
def edit_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    departments = Department.query.order_by(Department.name).all()
    managers = Employee.query.filter(Employee.id != emp_id,
                                     Employee.is_active == True).order_by(Employee.last_name).all()
    agrs = EmploymentAgreement.query.order_by(EmploymentAgreement.name).all()
    if request.method == 'POST':
        emp.first_name = request.form.get('first_name', '').strip()
        emp.last_name = request.form.get('last_name', '').strip()
        emp.email = request.form.get('email', '').strip()
        emp.phone = request.form.get('phone', '').strip()
        emp.job_title = request.form.get('job_title', '').strip()
        emp.department_id = request.form.get('department_id') or None
        emp.manager_id = request.form.get('manager_id') or None
        emp.agreement_id = request.form.get('agreement_id') or None
        emp.is_active = 'is_active' in request.form
        hire_date_str = request.form.get('hire_date', '')
        if hire_date_str:
            emp.hire_date = date.fromisoformat(hire_date_str)
        if not emp.first_name or not emp.last_name or not emp.email:
            flash('First name, last name and email are required.', 'danger')
            return render_template('employees/form.html', action='Edit', emp=emp,
                                   departments=departments, managers=managers, agreements=agrs)
        db.session.commit()
        flash(f'Employee {emp.full_name} updated successfully.', 'success')
        return redirect(url_for('view_employee', emp_id=emp_id))
    return render_template('employees/form.html', action='Edit', emp=emp,
                           departments=departments, managers=managers, agreements=agrs)


@app.route('/employees/<int:emp_id>/delete', methods=['POST'])
def delete_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    name = emp.full_name
    TimeEntry.query.filter_by(employee_id=emp_id).delete()
    db.session.delete(emp)
    db.session.commit()
    flash(f'Employee {name} deleted.', 'success')
    return redirect(url_for('employees'))


# ─── Time Tracking ───────────────────────────────────────────────────────────

@app.route('/time')
def time_tracking():
    active_employees = Employee.query.filter_by(is_active=True).order_by(
        Employee.last_name, Employee.first_name).all()
    # Build shift data map for JS
    employee_shifts = {}
    for emp in active_employees:
        if emp.agreement and emp.agreement.pay_type == 'shift':
            employee_shifts[emp.id] = [
                {'id': st.id, 'name': st.name,
                 'start': st.start_time.strftime('%H:%M'),
                 'end': st.end_time.strftime('%H:%M')}
                for st in emp.agreement.shift_templates
            ]
    return render_template('time/index.html', employees=active_employees,
                           employee_shifts_json=json.dumps(employee_shifts))


@app.route('/time/clock-in', methods=['POST'])
def clock_in():
    emp_id = request.form.get('employee_id')
    notes = request.form.get('notes', '').strip()
    shift_template_id = request.form.get('shift_template_id') or None
    if not emp_id:
        flash('Please select an employee.', 'danger')
        return redirect(url_for('time_tracking'))
    emp = Employee.query.get_or_404(emp_id)
    if emp.is_clocked_in:
        flash(f'{emp.full_name} is already clocked in.', 'warning')
        return redirect(url_for('time_tracking'))
    entry = TimeEntry(employee_id=emp.id, clock_in=datetime.utcnow(),
                      notes=notes, shift_template_id=shift_template_id)
    db.session.add(entry)
    db.session.commit()
    flash(f'{emp.full_name} clocked in at {entry.clock_in.strftime("%H:%M")}.', 'success')
    return redirect(url_for('time_tracking'))


@app.route('/time/clock-out', methods=['POST'])
def clock_out():
    emp_id = request.form.get('employee_id')
    if not emp_id:
        flash('Please select an employee.', 'danger')
        return redirect(url_for('time_tracking'))
    emp = Employee.query.get_or_404(emp_id)
    entry = emp.active_entry
    if not entry:
        flash(f'{emp.full_name} is not clocked in.', 'warning')
        return redirect(url_for('time_tracking'))
    entry.clock_out = datetime.utcnow()
    db.session.commit()
    flash(f'{emp.full_name} clocked out. Hours worked: {entry.duration_hours}', 'success')
    return redirect(url_for('time_tracking'))


@app.route('/time/report')
def time_report():
    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')
    emp_filter = request.args.get('employee_id', '')

    query = TimeEntry.query.filter(TimeEntry.clock_out.isnot(None))
    if date_from_str:
        query = query.filter(TimeEntry.clock_in >= datetime.strptime(date_from_str, '%Y-%m-%d'))
    if date_to_str:
        dt_to = datetime.strptime(date_to_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        query = query.filter(TimeEntry.clock_in <= dt_to)
    if emp_filter:
        query = query.filter_by(employee_id=emp_filter)

    entries = query.order_by(TimeEntry.clock_in.desc()).all()
    holiday_dates = get_holiday_dates()
    enriched = enrich_entries(entries, holiday_dates)
    total_hours = sum(e['entry'].duration_hours for e in enriched if e['entry'].duration_hours)
    employees_list = Employee.query.filter_by(is_active=True).order_by(Employee.last_name).all()

    return render_template('time/report.html',
                           enriched=enriched,
                           total_hours=round(total_hours, 2),
                           employees=employees_list,
                           date_from=date_from_str, date_to=date_to_str,
                           emp_filter=emp_filter)


# ─── DB init & migration ─────────────────────────────────────────────────────

def run_migrations():
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    if 'employees' in tables:
        cols = [c['name'] for c in inspector.get_columns('employees')]
        if 'agreement_id' not in cols:
            db.session.execute(text(
                'ALTER TABLE employees ADD COLUMN agreement_id INTEGER '
                'REFERENCES employment_agreements(id)'
            ))
            db.session.commit()

    if 'time_entries' in tables:
        cols = [c['name'] for c in inspector.get_columns('time_entries')]
        if 'shift_template_id' not in cols:
            db.session.execute(text(
                'ALTER TABLE time_entries ADD COLUMN shift_template_id INTEGER '
                'REFERENCES shift_templates(id)'
            ))
            db.session.commit()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        run_migrations()
    app.run(debug=True, port=5000)

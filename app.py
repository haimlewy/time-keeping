from flask import Flask, render_template, request, redirect, url_for, flash
from extensions import db
from models import Department, Employee, TimeEntry
from datetime import datetime, date

app = Flask(__name__)
app.config['SECRET_KEY'] = 'timekeeping-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///timekeeping.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}


# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    total_employees = Employee.query.filter_by(is_active=True).count()
    total_departments = Department.query.count()
    clocked_in = TimeEntry.query.filter_by(clock_out=None).count()
    recent_entries = (TimeEntry.query
                      .order_by(TimeEntry.clock_in.desc())
                      .limit(10).all())
    return render_template('dashboard.html',
                           total_employees=total_employees,
                           total_departments=total_departments,
                           clocked_in=clocked_in,
                           recent_entries=recent_entries)


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
                           departments=depts, dept_filter=dept_filter,
                           search=search)


@app.route('/employees/add', methods=['GET', 'POST'])
def add_employee():
    departments = Department.query.order_by(Department.name).all()
    managers = Employee.query.filter_by(is_active=True).order_by(
        Employee.last_name).all()
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        job_title = request.form.get('job_title', '').strip()
        department_id = request.form.get('department_id') or None
        manager_id = request.form.get('manager_id') or None
        hire_date_str = request.form.get('hire_date', '')

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
            return render_template('employees/form.html', action='Add',
                                   emp=None, departments=departments,
                                   managers=managers)

        hire_date = date.fromisoformat(hire_date_str) if hire_date_str else date.today()
        emp = Employee(first_name=first_name, last_name=last_name, email=email,
                       phone=phone, job_title=job_title,
                       department_id=department_id, manager_id=manager_id,
                       hire_date=hire_date)
        db.session.add(emp)
        db.session.commit()
        flash(f'Employee {emp.full_name} added successfully.', 'success')
        return redirect(url_for('employees'))
    return render_template('employees/form.html', action='Add', emp=None,
                           departments=departments, managers=managers)


@app.route('/employees/<int:emp_id>')
def view_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    entries = (TimeEntry.query.filter_by(employee_id=emp_id)
               .order_by(TimeEntry.clock_in.desc()).limit(20).all())
    total_hours = sum(e.duration_hours for e in entries if e.duration_hours)
    return render_template('employees/view.html', emp=emp, entries=entries,
                           total_hours=round(total_hours, 2))


@app.route('/employees/<int:emp_id>/edit', methods=['GET', 'POST'])
def edit_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    departments = Department.query.order_by(Department.name).all()
    managers = Employee.query.filter(Employee.id != emp_id, Employee.is_active == True).order_by(
        Employee.last_name).all()
    if request.method == 'POST':
        emp.first_name = request.form.get('first_name', '').strip()
        emp.last_name = request.form.get('last_name', '').strip()
        emp.email = request.form.get('email', '').strip()
        emp.phone = request.form.get('phone', '').strip()
        emp.job_title = request.form.get('job_title', '').strip()
        emp.department_id = request.form.get('department_id') or None
        emp.manager_id = request.form.get('manager_id') or None
        emp.is_active = 'is_active' in request.form
        hire_date_str = request.form.get('hire_date', '')
        if hire_date_str:
            emp.hire_date = date.fromisoformat(hire_date_str)

        if not emp.first_name or not emp.last_name or not emp.email:
            flash('First name, last name and email are required.', 'danger')
            return render_template('employees/form.html', action='Edit', emp=emp,
                                   departments=departments, managers=managers)
        db.session.commit()
        flash(f'Employee {emp.full_name} updated successfully.', 'success')
        return redirect(url_for('view_employee', emp_id=emp_id))
    return render_template('employees/form.html', action='Edit', emp=emp,
                           departments=departments, managers=managers)


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
    employees = Employee.query.filter_by(is_active=True).order_by(
        Employee.last_name, Employee.first_name).all()
    return render_template('time/index.html', employees=employees)


@app.route('/time/clock-in', methods=['POST'])
def clock_in():
    emp_id = request.form.get('employee_id')
    notes = request.form.get('notes', '').strip()
    if not emp_id:
        flash('Please select an employee.', 'danger')
        return redirect(url_for('time_tracking'))
    emp = Employee.query.get_or_404(emp_id)
    if emp.is_clocked_in:
        flash(f'{emp.full_name} is already clocked in.', 'warning')
        return redirect(url_for('time_tracking'))
    entry = TimeEntry(employee_id=emp.id, clock_in=datetime.utcnow(), notes=notes)
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
        dt_from = datetime.strptime(date_from_str, '%Y-%m-%d')
        query = query.filter(TimeEntry.clock_in >= dt_from)
    if date_to_str:
        dt_to = datetime.strptime(date_to_str, '%Y-%m-%d').replace(
            hour=23, minute=59, second=59)
        query = query.filter(TimeEntry.clock_in <= dt_to)
    if emp_filter:
        query = query.filter_by(employee_id=emp_filter)

    entries = query.order_by(TimeEntry.clock_in.desc()).all()
    total_hours = sum(e.duration_hours for e in entries if e.duration_hours)
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.last_name).all()

    return render_template('time/report.html', entries=entries,
                           total_hours=round(total_hours, 2),
                           employees=employees,
                           date_from=date_from_str, date_to=date_to_str,
                           emp_filter=emp_filter)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)

# =================================================
# OSHAQUE CLOUDFEES ERP SYSTEM
# Complete College Fees Management System
# Technology: Flask, Azure SQL Database
# =================================================

# ==================== IMPORTS ====================
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from datetime import datetime, date
from io import BytesIO
import os
import hashlib
import pyodbc
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ModuleNotFoundError:
    pd = None
    PANDAS_AVAILABLE = False
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# ==================== FLASK APP CONFIGURATION ====================
app = Flask(__name__)
app.secret_key = 'oshaque-cloudfees-secret-key-2024'
app.config['DEBUG'] = True
app.config['PROPAGATE_EXCEPTIONS'] = True
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads directory for images and documents
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'docx'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==================== DATABASE CONNECTION FUNCTION ====================

def get_db_connection():
    """Establishes connection to Azure SQL Database."""
    conn_str = os.environ.get('AZURE_SQL_CONNECTIONSTRING',
        "Driver={ODBC Driver 18 for SQL Server};"
        "Server=tcp:sqldbdserver012.database.windows.net,1433;"
        "Database=OSHAQUE-FEES-SYSTEM-DB;"
        "Uid=sqldbdserver012-admin;"
        "Pwd=aNH4XTXWF$sA01$R;"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;")
    return pyodbc.connect(conn_str)

# ==================== HELPER FUNCTIONS ====================

def allowed_file(filename):
    """Check if uploaded file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def md5_password(password):
    """Return an MD5 password hash for backward compatibility."""
    return hashlib.md5(password.encode()).hexdigest()


def hash_password(password):
    """Return a SHA-256 password hash."""
    return hashlib.sha256(password.encode()).hexdigest()


def generate_student_id():
    """Generate unique student ID (e.g., STU-0001)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM students")
    count = cursor.fetchone()[0]
    conn.close()
    return f"STU-{count+1:04d}"


def generate_receipt_no():
    """Generate unique receipt number (e.g., RCPT-202400001)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM fee_receipts")
    count = cursor.fetchone()[0]
    conn.close()
    return f"RCPT-{datetime.now().strftime('%Y%m%d')}-{count+1:04d}"


def get_settings():
    """Fetch all system settings from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_key, setting_value FROM settings")
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return {}

# ==================== ROLE / PERMISSION SYSTEM ====================

ROLES = {'super_admin', 'admin', 'accountant', 'student', 'parent'}


def get_logged_in_student_id():
    """Return logged-in student_id for role=student.

    Mapping per your DB reality:
    - users.email == students.email
    """
    if current_role() != 'student':
        return None

    if not session.get('email'):
        return None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT TOP 1 student_id FROM students WHERE email = ? AND is_active=1",
            (session.get('email'),),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()



def get_child_student_ids_for_parent():
    """Return child student_ids for logged-in parent.

    Mapping per your DB reality:
    - parent_child.parent_id == users.id (session['user_id'])
    """
    if current_role() != 'parent':
        return None

    parent_user_id = session.get('user_id')
    if not parent_user_id:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT student_id FROM parent_child WHERE parent_id = ?",
            (parent_user_id,),
        )
        rows = cursor.fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()



def require_login():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return None


def require_role_any(*allowed_roles):
    """Route guard; super_admin always allowed."""
    resp = require_login()
    if resp is not None:
        return resp

    role = current_role()
    if role == 'super_admin':
        return None
    if role not in allowed_roles:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    return None


def deny_json(reason='Access denied'):
    return jsonify({'success': False, 'error': reason}), 403


# Permissions are expressed per module/action.
# The matrix requested by user is enforced through route guards.
PERMISSIONS = {
     # Dashboard: view dashboards with correct data scoping.

    'dashboard': {
        'super_admin': {'view'},
        'admin': {'view'},
        'accountant': {'view'},
        'student': {'view_own'},
        'parent': {'view_child'},
    },
    # Students management
    'students': {
        'super_admin': {'full'},
        'admin': {'full'},
        'accountant': {'view_only'},
        'student': set(),
        'parent': set(),
    },
    # Fee Structure
    'fee_structure': {
        'super_admin': {'full'},
        'admin': {'full'},
        'accountant': {'view_only'},
        'student': {'view_only'},
        'parent': {'view_only'},
    },
    # Collection
    'collection': {
        'super_admin': {'full'},
        'admin': {'full'},
        'accountant': {'full'},
        'student': set(),
        'parent': set(),
    },
    # Payment history
    'payment_history': {
        'super_admin': {'view_all'},
        'admin': {'view_all'},
        'accountant': {'view_all'},
        'student': {'view_own'},
        'parent': {'view_child'},
    },
    # Receipts
    'receipts': {
        'super_admin': {'view_all', 'download_all'},
        'admin': {'view_all', 'download_all'},
        'accountant': {'view_all', 'download_all'},
        'student': {'view_own', 'download_own'},
        'parent': {'view_child', 'download_child'},
    },
    # Defaulters
    'defaulters': {
        'super_admin': {'view_full'},
        'admin': {'view_full'},
        'accountant': {'view_full'},
        'student': set(),
        'parent': set(),
    },
    # Reports
    'reports': {
        'super_admin': {'view'},
        'admin': {'view'},
        'accountant': {'view'},
        'student': set(),
        'parent': set(),
    },
    # Expenses
    'expenses': {
        'super_admin': {'full'},
        'admin': {'full'},
        'accountant': {'add_view'},
        'student': set(),
        'parent': set(),
    },
    # Courses
    'courses': {
        'super_admin': {'view_full'},
        'admin': {'view_full'},
        'accountant': {'view_only'},
        'student': {'view_only'},
        'parent': {'view_only'},
    },
    # Users
    'users': {
        'super_admin': {'full'},
        'admin': set(),
        'accountant': set(),
        'student': set(),
        'parent': set(),
    },
    # Settings
    'settings': {
        'super_admin': {'limited'},
        'admin': {'limited'},
        'accountant': set(),
        'student': set(),
        'parent': set(),
    },
    # Approvals
    'approvals': {
        'super_admin': {'full'},
        'admin': {'full'},
        'accountant': set(),
        'student': set(),
        'parent': set(),
    },
}


def current_role():
    return session.get('role')


def deny(reason='Access denied'):
    flash(reason, 'error')
    return redirect(url_for('login'))


def require_role(*allowed_roles):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    role = current_role()
    if role not in allowed_roles:
        return deny('Access denied')
    return None


def require_permission(module_key, required_perm):
    """Route-level guard (SUPER_ADMIN bypasses).

    Returns redirect/deny response when not authorized, otherwise None.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    role = current_role()
    if role == 'super_admin':
        return None

    allowed = PERMISSIONS.get(module_key, {}).get(role, set())
    if required_perm not in allowed:
        return deny('Access denied')
    return None



def get_student_user_context():
    """Compatibility wrapper used by existing code.

    Now implemented via correct mapping:
    - users.email == students.email
    """
    return get_logged_in_student_id()



def get_parent_child_context():
    """Compatibility wrapper used by existing code.

    Now uses correct mapping:
    - parent_child.parent_id == session['user_id']
    """
    return get_child_student_ids_for_parent()



def get_scoped_payment_filter():
    """Build SQL WHERE clause for fee_payments scope (Student/Parent).

    Mapping per your DB reality:
    - Student scope: users.email -> students.email -> students.student_id
    - Parent scope: parent_child.parent_id == session['user_id'] -> child students
    """

    role = current_role()

    if role == 'student':
        student_id = get_logged_in_student_id()
        if not student_id:
            return " AND 1=0 ", []
        return " AND fp.student_id = ? ", [student_id]

    if role == 'parent':
        child_ids = get_child_student_ids_for_parent()
        if not child_ids:
            return " AND 1=0 ", []
        placeholders = ','.join(['?'] * len(child_ids))
        return f" AND fp.student_id IN ({placeholders}) ", child_ids

    return "", []



# ==================== UI CONTEXT PROCESSORS ====================

@app.context_processor
def inject_settings():
    return {
        'settings': get_settings(),
        'sidebar_links': get_sidebar_links_safe(),
    }


def get_sidebar_links_safe():
    """Sidebar items should match permissions, but this is UI-only.
    Backend is guarded separately.
    """
    role = current_role()
    links = [
        {'url': '/dashboard', 'icon': 'fas fa-chart-line', 'label': 'Dashboard', 'module': 'dashboard'},
        {'url': '/collection', 'icon': 'fas fa-hand-holding-usd', 'label': 'Collection', 'module': 'collection'},
        {'url': '/payment_history', 'icon': 'fas fa-history', 'label': 'Payment History', 'module': 'payment_history'},
        {'url': '/reports', 'icon': 'fas fa-chart-bar', 'label': 'Reports', 'module': 'reports'},
        {'url': '/expenses', 'icon': 'fas fa-money-bill-wave', 'label': 'Expenses', 'module': 'expenses'},
    ]

    # Replace module lists for admin-like roles
    if role in ['super_admin', 'admin', 'accountant']:
        # Collection is allowed for admin/accountant
        links[1:1] = [
            {'url': '/students', 'icon': 'fas fa-user-graduate', 'label': 'Students', 'module': 'students'},
            {'url': '/fee_structure', 'icon': 'fas fa-file-invoice-dollar', 'label': 'Fee Structure', 'module': 'fee_structure'},
            {'url': '/defaulters', 'icon': 'fas fa-exclamation-triangle', 'label': 'Defaulters', 'module': 'defaulters'},
            {'url': '/advanced', 'icon': 'fas fa-bolt', 'label': 'Advanced', 'module': 'advanced'},
            {'url': '/courses', 'icon': 'fas fa-book', 'label': 'Courses', 'module': 'courses'},
        ]
        if role in ['super_admin', 'admin']:
            links.insert(1, {'url': '/approvals', 'icon': 'fas fa-user-shield', 'label': 'Approvals', 'module': 'approvals'})

        # Settings visible for admin/super_admin only
        if role in ['super_admin', 'admin']:
            links.append({'url': '/settings', 'icon': 'fas fa-cog', 'label': 'Settings', 'module': 'settings'})

    # Student/Parent: only dashboard + fee structure + own payment/receipts should be visible
    if role in ['student', 'parent']:
        links = [
            {'url': '/dashboard', 'icon': 'fas fa-chart-line', 'label': 'Dashboard', 'module': 'dashboard'},
            {'url': '/fee_structure', 'icon': 'fas fa-file-invoice-dollar', 'label': 'Fee Structure', 'module': 'fee_structure'},
            {'url': '/payment_history', 'icon': 'fas fa-history', 'label': 'My Payments', 'module': 'payment_history'},
            {'url': '/collection', 'icon': 'fas fa-hand-holding-usd', 'label': ' ', 'module': 'collection'},
        ]
        # Hide collection link visually by removing it
        links = [l for l in links if l['url'] != '/collection']

    if role == 'super_admin':
        links.append({'url': '/users', 'icon': 'fas fa-users-cog', 'label': 'Users', 'module': 'users'})

    links.append({'url': '/logout', 'icon': 'fas fa-sign-out-alt', 'label': 'Logout', 'module': 'logout'})
    return links


# ==================== EMAIL NOTIFICATIONS ====================

def send_email_notification(to_email, subject, body, attachment_path=None):
    try:
        settings = get_settings()
        smtp_server = settings.get('smtp_server', 'smtp.gmail.com')
        smtp_port = int(settings.get('smtp_port', 587))
        smtp_user = settings.get('smtp_user', '')
        smtp_password = settings.get('smtp_password', '')

        if not smtp_user or not smtp_password:
            print("SMTP not configured")
            return False

        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(attachment_path)}')
                msg.attach(part)

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


# ==================== AUTHENTICATION ROUTES ====================

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        raw_password = request.form.get('password', '')
        password_sha256 = hash_password(raw_password)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, role, password, email FROM users WHERE username=? AND is_active=1",
            (username,)
        )
        user = cursor.fetchone()
        if user:
            stored_password = user[3]
            if stored_password == password_sha256:
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['role'] = user[2]
                session['email'] = user[4]
                conn.close()
                return redirect(url_for('dashboard'))

            if stored_password == md5_password(raw_password):
                cursor.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (password_sha256, user[0])
                )
                conn.commit()
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['role'] = user[2]
                session['email'] = user[4]
                conn.close()
                return redirect(url_for('dashboard'))

        conn.close()
        return render_template('login.html', error='Invalid credentials', username=username)

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    # keep existing behavior
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, course_name FROM courses WHERE is_active=1")
        courses = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"Error loading courses: {e}")
        return render_template('register.html', error='Unable to load registration form', courses=[], form_data={})

    if request.method == 'POST':
        form_data = {
            'name': request.form.get('name', '').strip(),
            'email': request.form.get('email', '').strip(),
            'phone': request.form.get('phone', '').strip(),
            'parent_name': request.form.get('parent_name', '').strip(),
            'parent_phone': request.form.get('parent_phone', '').strip(),
            'course_id': request.form.get('course_id', '').strip(),
            'address': request.form.get('address', '').strip(),
            'username': request.form.get('username', '').strip(),
            'role': request.form.get('role', 'student').strip().lower(),
        }

        password_raw = request.form.get('password', '')
        password_confirm = request.form.get('confirm_password', '')

        if not all([
            form_data['name'], form_data['email'], form_data['phone'],
            form_data['parent_name'], form_data['parent_phone'],
            form_data['course_id'], form_data['username'],
            password_raw, password_confirm
        ]):
            return render_template('register.html', error='All fields are required.', courses=courses, form_data=form_data)

        if password_raw != password_confirm:
            return render_template('register.html', error='Passwords do not match.', courses=courses, form_data=form_data)

        if len(password_raw) < 6:
            return render_template('register.html', error='Password must be at least 6 characters.', courses=courses, form_data=form_data)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM users WHERE username=?", (form_data['username'],))
            if cursor.fetchone():
                conn.close()
                return render_template('register.html', error='Username already exists!', courses=courses, form_data=form_data)

            password = hash_password(password_raw)
            cursor.execute(
                """
                INSERT INTO registration_requests
                (name, email, phone, parent_name, parent_phone, course_id, address, username, password, role, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending')
                """,
                (
                    form_data['name'], form_data['email'], form_data['phone'],
                    form_data['parent_name'], form_data['parent_phone'],
                    form_data['course_id'], form_data['address'],
                    form_data['username'], password, form_data['role']
                )
            )
            conn.commit()
            conn.close()

            return render_template('register.html', success='Registration request sent! Wait for admin approval.', courses=courses, form_data={})
        except Exception as e:
            print(f"Registration error: {e}")
            conn.close()
            return render_template('register.html', error='Registration failed. Please try again.', courses=courses, form_data=form_data)

    return render_template('register.html', courses=courses, form_data={})


# ==================== IDOR HELPERS (data-level validation) ====================

def is_student_id_in_logged_in_scope(student_id: str) -> bool:
    role = current_role()
    if role == 'super_admin':
        return True
    if role == 'student':
        return str(get_logged_in_student_id() or '') == str(student_id)
    if role == 'parent':
        return str(student_id) in {str(x) for x in (get_child_student_ids_for_parent() or [])}
    return False


def is_payment_id_in_logged_in_scope(payment_id: int) -> bool:
    """Checks that payment belongs to logged-in student/parent scope."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT student_id FROM fee_payments WHERE id = ?", (payment_id,))
        row = cursor.fetchone()
        if not row:
            return False
        return is_student_id_in_logged_in_scope(row[0])
    except Exception:
        return False
    finally:
        conn.close()

# ==================== DASHBOARD ROUTE ====================

@app.route('/dashboard')
def dashboard():

    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        role = current_role()

        conn = get_db_connection()
        cursor = conn.cursor()

        today = date.today().strftime('%Y-%m-%d')
        current_month = date.today().strftime('%Y-%m')

        # Scope data for student/parent
        payment_filter, payment_params = get_scoped_payment_filter().split(' AND ', 1) if role in ['student', 'parent'] else ('', [])
        # Simpler: call helper returns full clause with leading AND.
        fp_clause, fp_params = get_scoped_payment_filter()

        # Daily
        cursor.execute(f"SELECT ISNULL(SUM(amount), 0) FROM fee_payments fp WHERE CAST(fp.created_at AS DATE) = ? {fp_clause}", [today] + fp_params)
        today_collection = float(cursor.fetchone()[0] or 0)

        cursor.execute(f"SELECT COUNT(*) FROM fee_payments fp WHERE CAST(fp.created_at AS DATE) = ? {fp_clause}", [today] + fp_params)
        today_count = cursor.fetchone()[0] or 0

        cursor.execute(f"SELECT ISNULL(SUM(amount), 0) FROM fee_payments fp WHERE FORMAT(fp.payment_date, 'yyyy-MM') = ? {fp_clause}", [current_month] + fp_params)
        monthly_collection = float(cursor.fetchone()[0] or 0)

        # Total students / defaulters: keep original for admin; for student/parent show personal pending fees.
        if role in ['admin', 'accountant', 'super_admin']:
            cursor.execute("SELECT COUNT(*) FROM students WHERE is_active=1")
            total_students = cursor.fetchone()[0] or 0
            cursor.execute("SELECT ISNULL(SUM(amount), 0) FROM fee_payments")
            total_collected = float(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT ISNULL(SUM(due_amount), 0) FROM fee_defaulters")
            pending_fees = float(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COUNT(DISTINCT student_id) FROM fee_defaulters WHERE due_amount > 0")
            defaulters_count = cursor.fetchone()[0] or 0
        else:
            # Student/Parent scoped pending fees
            cursor.execute(
                f"SELECT ISNULL(SUM(due_amount), 0) FROM fee_defaulters fd WHERE 1=1 {fp_clause.replace('fp.', 'fd.')}",
                fp_params
            )
            pending_fees = float(cursor.fetchone()[0] or 0)
            defaulters_count = 1 if pending_fees > 0 else 0
            total_students = 0
            total_collected = today_collection

        # Recent payments
        cursor.execute(
            f"""
            SELECT TOP 5 fp.id, s.name, fp.amount, fp.payment_date, fp.payment_mode
            FROM fee_payments fp
            JOIN students s ON fp.student_id = s.student_id
            WHERE 1=1 {fp_clause}
            ORDER BY fp.created_at DESC
            """
            , fp_params
        )
        recent_payments = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT fp.payment_mode, ISNULL(SUM(fp.amount), 0)
            FROM fee_payments fp
            WHERE FORMAT(fp.payment_date, 'yyyy-MM') = ? {fp_clause}
            GROUP BY fp.payment_mode
            """,
            [current_month] + fp_params
        )
        payment_modes = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT FORMAT(fp.payment_date, 'MMM yyyy') as month, ISNULL(SUM(fp.amount), 0)
            FROM fee_payments fp
            WHERE fp.payment_date >= DATEADD(month, -6, GETDATE()) {fp_clause}
            GROUP BY FORMAT(fp.payment_date, 'MMM yyyy'), MONTH(fp.payment_date)
            ORDER BY MIN(fp.payment_date)
            """,
            fp_params
        )
        monthly_trend = cursor.fetchall()

        conn.close()

        settings = get_settings()

        return render_template(
            'index.html',
            module='dashboard',
            role=role,
            today_collection=today_collection,
            today_count=today_count,
            monthly_collection=monthly_collection,
            total_students=total_students,
            total_collected=total_collected,
            pending_fees=pending_fees,
            defaulters_count=defaulters_count,
            recent_payments=recent_payments,
            payment_modes=payment_modes,
            monthly_trend=monthly_trend,
            settings=settings,
        )

    except Exception as e:
        print(f"Dashboard error: {e}")
        return render_template('index.html', module='dashboard', role=current_role(), error=str(e))


# ==================== STUDENTS MANAGEMENT ROUTES ====================

@app.route('/students')
def students():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Keep access consistent with sidebar/admin usage
    if session.get('role') not in ['super_admin', 'admin', 'accountant']:
        return redirect(url_for('dashboard'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT student_id, name, roll_no, course_id, semester_id, parent_name, parent_phone, parent_email
            FROM students
            WHERE is_active=1
            ORDER BY name
            """
        )
        students_list = cursor.fetchall()
        conn.close()

        # Admin module: show only real student records (not other user roles)
        # Template expects module == 'students'.
        return render_template(
            'index.html',
            module='students',
            role=session.get('role'),
            students=students_list,
            settings=get_settings(),
            courses=[],
            semesters=[],
            search=request.args.get('search', ''),
            selected_course=request.args.get('course_id', ''),
            selected_status=request.args.get('status', ''),
        )
    except Exception as e:
        print(f"View student error: {e}")
        return redirect(url_for('students'))


# ==================== FEE STRUCTURE ROUTES ====================
@app.route('/fee_structure')
def fee_structure():
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT fs.id, c.course_name, sem.semester_name, fh.head_name, fs.amount, fs.due_date
            FROM fee_structures fs
            JOIN courses c ON fs.course_id = c.id
            JOIN semesters sem ON fs.semester_id = sem.id
            JOIN fee_heads fh ON fs.fee_head_id = fh.id
            ORDER BY c.course_name, sem.semester_no, fh.display_order
            """
        )
        fee_structures = cursor.fetchall()

        cursor.execute("SELECT id, course_name FROM courses WHERE is_active=1")
        courses = cursor.fetchall()

        cursor.execute("SELECT id, semester_name, semester_no FROM semesters ORDER BY course_id, semester_no")
        semesters = cursor.fetchall()

        cursor.execute("SELECT id, head_name FROM fee_heads WHERE is_active=1 ORDER BY display_order")
        fee_heads = cursor.fetchall()

        conn.close()

        return render_template(
            'index.html',
            module='fee_structure',
            role=session.get('role'),
            fee_structures=fee_structures,
            courses=courses,
            semesters=semesters,
            fee_heads=fee_heads,
        )
    except Exception as e:
        print(f"Fee structure error: {e}")
        return render_template('index.html', module='fee_structure', role=session.get('role'), error=str(e))


@app.route('/get_semesters/<int:course_id>')
def get_semesters(course_id):
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, semester_name, semester_no
            FROM semesters
            WHERE course_id = ?
            ORDER BY semester_no
            """,
            (course_id,),
        )
        rows = cursor.fetchall()
        conn.close()

        return jsonify({
            'success': True,
            'semesters': [
                {'id': int(r[0]), 'name': str(r[1])}
                for r in rows
            ]
        })
    except Exception as e:
        print(f"Get semesters error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/add_fee_structure', methods=['POST'])
def add_fee_structure():
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return redirect(url_for('login'))

    try:
        course_id = int(request.form['course_id'])
        semester_id = int(request.form['semester_id'])
        fee_head_id = int(request.form['fee_head_id'])
        amount = float(request.form['amount'])
        due_date = request.form.get('due_date')

        conn = get_db_connection()
        cursor = conn.cursor()

        # FRONTEND-ONLY SEMESTERS NOTE
        # Your semesters table may be empty and you want semesters to be generated on the frontend.
        # Therefore, we do NOT validate semester_id against the semesters table.
        # We save the provided semester number directly as semester_no.

        # Map the posted semester_id to semester_no.
        semester_no = semester_id


        cursor.execute(
            """
            INSERT INTO fee_structures (course_id, semester_id, fee_head_id, amount, due_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (course_id, semester_id, fee_head_id, amount, due_date),
        )
        conn.commit()
        conn.close()

        return redirect(url_for('fee_structure'))
    except Exception as e:
        print(f"Add fee structure error: {e}")
        return redirect(url_for('fee_structure'))



@app.route('/delete_fee_structure/<int:id>')
def delete_fee_structure(id):
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fee_structures WHERE id=?", (id,))
        conn.commit()
        conn.close()
        return redirect(url_for('fee_structure'))
    except Exception as e:
        print(f"Delete fee structure error: {e}")
        return redirect(url_for('fee_structure'))

# ==================== FEE COLLECTION ROUTES ====================
@app.route('/collection')
def collection():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT student_id, name, roll_no, course_id
            FROM students WHERE is_active=1 ORDER BY name
            """
        )
        students = cursor.fetchall()
        conn.close()
        settings = get_settings()

        return render_template('index.html', module='collection', role=session.get('role'), students=students, settings=settings)
    except Exception as e:
        print(f"Collection page error: {e}")
        return render_template('index.html', module='collection', role=session.get('role'), error=str(e))


@app.route('/get_student_fees/<student_id>')
def get_student_fees(student_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT s.name, s.roll_no, c.course_name, sem.semester_name, s.course_id, s.semester_id
            FROM students s
            JOIN courses c ON s.course_id = c.id
            JOIN semesters sem ON s.semester_id = sem.id
            WHERE s.student_id=?
            """,
            (student_id,),
        )
        student = cursor.fetchone()

        if not student:
            return jsonify({'error': 'Student not found'})

        cursor.execute(
            """
            SELECT 
                fh.id as fee_head_id,
                fh.head_name,
                fs.amount as head_total,
                fs.due_date,
                ISNULL((
                    SELECT SUM(pd.amount)
                    FROM fee_payments fp
                    JOIN payment_details pd ON fp.id = pd.payment_id
                    WHERE fp.student_id = ?
                      AND pd.fee_head_id = fh.id
                      AND fp.status = 'Completed'
                ), 0) as paid_amount
            FROM fee_structures fs
            JOIN fee_heads fh ON fs.fee_head_id = fh.id
            WHERE fs.course_id = ? AND fs.semester_id = ?
            """,
            (student_id, student[4], student[5]),
        )
        fee_heads_data = cursor.fetchall()

        total_fee = sum(row[2] for row in fee_heads_data)
        total_paid = sum(row[4] for row in fee_heads_data)
        pending_amount = total_fee - total_paid

        conn.close()

        return jsonify(
            {
                'success': True,
                'student_name': student[0],
                'roll_no': student[1],
                'course': student[2],
                'semester': student[3],
                'total_fee': float(total_fee),
                'total_paid': float(total_paid),
                'pending_amount': float(pending_amount),
                'fee_heads': [
                    {
                        'fee_head_id': int(row[0]),
                        'head_name': row[1],
                        'head_total': float(row[2]),
                        'paid_amount': float(row[4]),
                        'pending_amount': float(row[2]) - float(row[4]),
                    }
                    for row in fee_heads_data
                ],
            }
        )
    except Exception as e:
        print(f"Get student fees error: {e}")
        return jsonify({'error': str(e)})


@app.route('/collect_fee', methods=['POST'])
def collect_fee():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    try:
        student_id = request.form['student_id']
        amount = float(request.form['amount'])
        payment_mode = request.form['payment_mode']
        transaction_id = request.form.get('transaction_id', '')
        cheque_number = request.form.get('cheque_number', '')
        bank_name = request.form.get('bank_name', '')
        remarks = request.form.get('remarks', '')
        fee_head_ids = request.form.getlist('fee_head_ids[]')
        fee_head_amounts = request.form.getlist('fee_head_amounts[]')

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO fee_payments (student_id, payment_date, amount, payment_mode,
                                      transaction_id, cheque_number, bank_name, remarks, collected_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (student_id, date.today(), amount, payment_mode, transaction_id, cheque_number, bank_name, remarks, session['user_id']),
        )
        cursor.execute("SELECT @@IDENTITY")
        payment_id = cursor.fetchone()[0]

        for i, head_id in enumerate(fee_head_ids):
            if head_id and i < len(fee_head_amounts):
                head_amount = float(fee_head_amounts[i])
                if head_amount > 0:
                    cursor.execute(
                        """
                        INSERT INTO payment_details (payment_id, fee_head_id, amount)
                        VALUES (?, ?, ?)
                        """,
                        (payment_id, head_id, head_amount),
                    )

        receipt_no = generate_receipt_no()
        cursor.execute(
            """
            INSERT INTO fee_receipts (receipt_no, payment_id, student_id, receipt_date)
            VALUES (?, ?, ?, ?)
            """,
            (receipt_no, payment_id, student_id, date.today()),
        )

        cursor.execute("DELETE FROM fee_defaulters WHERE student_id=?", (student_id,))

        conn.commit()
        conn.close()

        return jsonify({'success': True, 'receipt_no': receipt_no, 'payment_id': payment_id})
    except Exception as e:
        print(f"Collect fee error: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== RECEIPT ROUTES ====================
@app.route('/receipt/<int:payment_id>')
def view_receipt(payment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT fp.id, fp.student_id, fp.payment_date, fp.amount, fp.payment_mode,
                   fp.transaction_id, fp.cheque_number, fp.bank_name, fp.remarks,
                   fr.receipt_no, s.name, s.roll_no
            FROM fee_payments fp
            JOIN fee_receipts fr ON fp.id = fr.payment_id
            JOIN students s ON fp.student_id = s.student_id
            WHERE fp.id=?
            """,
            (payment_id,),
        )
        payment = cursor.fetchone()

        if not payment:
            return "Receipt not found", 404

        cursor.execute(
            """
            SELECT fh.head_name, pd.amount
            FROM payment_details pd
            JOIN fee_heads fh ON pd.fee_head_id = fh.id
            WHERE pd.payment_id=?
            """,
            (payment_id,),
        )
        fee_breakdown = cursor.fetchall()

        conn.close()

        settings = get_settings()

        return render_template(
            'index.html',
            module='view_receipt',
            role=session.get('role'),
            payment=payment,
            fee_breakdown=fee_breakdown,
            settings=settings,
        )
    except Exception as e:
        print(f"View receipt error: {e}")
        return "Receipt not found", 404


@app.route('/download_receipt_pdf/<int:payment_id>')
def download_receipt_pdf(payment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT fp.id, fp.student_id, fp.payment_date, fp.amount, fp.payment_mode,
                   fp.transaction_id, fp.cheque_number, fp.bank_name, fp.remarks,
                   fr.receipt_no, s.name, s.roll_no
            FROM fee_payments fp
            JOIN fee_receipts fr ON fp.id = fr.payment_id
            JOIN students s ON fp.student_id = s.student_id
            WHERE fp.id=?
            """,
            (payment_id,),
        )
        payment = cursor.fetchone()

        if not payment:
            return "Receipt not found", 404

        cursor.execute(
            """
            SELECT fh.head_name, pd.amount
            FROM payment_details pd
            JOIN fee_heads fh ON pd.fee_head_id = fh.id
            WHERE pd.payment_id=?
            """,
            (payment_id,),
        )
        fee_breakdown = cursor.fetchall()

        conn.close()

        settings = get_settings()

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()

        story = []

        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=18, alignment=1)
        story.append(Paragraph(settings.get('college_name', 'OSHAQUE College'), title_style))
        story.append(Paragraph("Fee Receipt", styles['Heading2']))
        story.append(Spacer(1, 12))

        receipt_data = [
            ['Receipt No:', payment[9]],
            ['Date:', payment[2].strftime('%d-%m-%Y') if payment[2] else ''],
            ['Student ID:', payment[1]],
            ['Student Name:', payment[10]],
            ['Roll No:', payment[11]],
            ['Payment Mode:', payment[4]],
        ]

        if payment[5]:
            receipt_data.append(['Transaction ID:', payment[5]])
        if payment[6]:
            receipt_data.append(['Cheque No:', payment[6]])
        if payment[7]:
            receipt_data.append(['Bank:', payment[7]])

        table = Table(receipt_data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

        breakdown_data = [['Fee Head', 'Amount']]
        for item in fee_breakdown:
            breakdown_data.append([item[0], f"Rs. {item[1]:,.2f}"])
        breakdown_data.append(['Total Amount', f"Rs. {payment[2]:,.2f}"])

        breakdown_table = Table(breakdown_data, colWidths=[4*inch, 2*inch])
        breakdown_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ]))
        story.append(breakdown_table)
        story.append(Spacer(1, 12))

        story.append(Paragraph(f"Amount in Words: {amount_to_words(payment[2])}", styles['Normal']))
        story.append(Paragraph("This is computer generated receipt. No signature required.", styles['Italic']))

        doc.build(story)
        buffer.seek(0)

        return send_file(buffer, as_attachment=True, download_name=f"receipt_{payment[9]}.pdf", mimetype='application/pdf')
    except Exception as e:
        print(f"Download PDF error: {e}")
        return "PDF generation failed", 500


def amount_to_words(amount):
    words = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]
    if amount < 11:
        return words[int(amount)] + " Rupees"
    return str(int(amount)) + " Rupees"

# ==================== PAYMENT HISTORY ROUTE ====================
@app.route('/payment_history')
def payment_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        student_id = request.args.get('student_id', '')
        from_date = request.args.get('from_date', '')
        to_date = request.args.get('to_date', '')

        query = """
            SELECT fp.id, s.name, s.student_id, fp.amount, fp.payment_date,
                   fp.payment_mode, fr.receipt_no
            FROM fee_payments fp
            JOIN students s ON fp.student_id = s.student_id
            LEFT JOIN fee_receipts fr ON fp.id = fr.payment_id
            WHERE 1=1
        """
        params = []

        if student_id:
            query += " AND fp.student_id = ?"
            params.append(student_id)

        if from_date:
            query += " AND fp.payment_date >= ?"
            params.append(from_date)

        if to_date:
            query += " AND fp.payment_date <= ?"
            params.append(to_date)

        query += " ORDER BY fp.payment_date DESC"
        cursor.execute(query, params)
        payments = cursor.fetchall()

        cursor.execute("SELECT student_id, name FROM students WHERE is_active=1 ORDER BY name")
        students = cursor.fetchall()

        conn.close()

        return render_template(
            'index.html',
            module='payment_history',
            role=session.get('role'),
            payments=payments,
            students=students,
            student_id=student_id,
            from_date=from_date,
            to_date=to_date,
        )
    except Exception as e:
        print(f"Payment history error: {e}")
        return render_template('index.html', module='payment_history', role=session.get('role'), error=str(e))

# ==================== DEFAULTERS ROUTE ====================
@app.route('/defaulters')
def defaulters():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT s.name, s.student_id, s.roll_no, s.parent_phone, s.parent_email,
                   fd.due_amount, fd.late_fee, fd.days_overdue
            FROM fee_defaulters fd
            JOIN students s ON fd.student_id = s.student_id
            WHERE fd.due_amount > 0
            ORDER BY fd.days_overdue DESC
            """
        )
        defaulters_list = cursor.fetchall()
        conn.close()

        settings = get_settings()

        return render_template(
            'index.html',
            module='defaulters',
            role=session.get('role'),
            defaulters=defaulters_list,
            settings=settings,
        )
    except Exception as e:
        print(f"Defaulters error: {e}")
        return render_template('index.html', module='defaulters', role=session.get('role'), error=str(e))


@app.route('/send_reminder/<student_id>')
def send_reminder(student_id):
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return jsonify({'success': False})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT s.name, s.parent_email, s.parent_phone, fd.due_amount
            FROM fee_defaulters fd
            JOIN students s ON fd.student_id = s.student_id
            WHERE fd.student_id=?
            """,
            (student_id,),
        )
        student = cursor.fetchone()

        if student and student[1]:
            subject = "Fee Payment Reminder"
            body = f"""
            <html>
            <body>
                <h3>Fee Payment Reminder</h3>
                <p>Dear Parent,</p>
                <p>This is to remind you that your child <strong>{student[0]}</strong> has pending fee of <strong>Rs. {student[3]}</strong>.</p>
                <p>Please clear the dues at the earliest to avoid late fee charges.</p>
                <br>
                <p>Thank you,<br>Accounts Department</p>
            </body>
            </html>
            """

            send_email_notification(student[1], subject, body)

        cursor.execute(
            "UPDATE fee_defaulters SET reminder_sent=1, reminder_date=? WHERE student_id=?",
            (date.today(), student_id),
        )
        conn.commit()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        print(f"Send reminder error: {e}")
        return jsonify({'success': False})


@app.route('/send_bulk_reminders')
def send_bulk_reminders():
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return jsonify({'success': False})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT s.student_id, s.name, s.parent_email, s.parent_phone, fd.due_amount "
            "FROM fee_defaulters fd "
            "JOIN students s ON fd.student_id = s.student_id "
            "WHERE fd.due_amount > 0"
        )
        defaulters = cursor.fetchall()

        sent_count = 0
        for row in defaulters:
            student_id, student_name, parent_email, parent_phone, due_amount = row
            if parent_email:
                subject = "Fee Payment Reminder"
                body = f"""
                <html>
                <body>
                    <h3>Fee Payment Reminder</h3>
                    <p>Dear Parent,</p>
                    <p>This is to remind you that your child <strong>{student_name}</strong> has pending fee of <strong>Rs. {due_amount}</strong>.</p>
                    <p>Please clear the dues at the earliest to avoid late fee charges.</p>
                    <br>
                    <p>Thank you,<br>Accounts Department</p>
                </body>
                </html>
                """
                if send_email_notification(parent_email, subject, body):
                    sent_count += 1

        cursor.execute(
            "UPDATE fee_defaulters SET reminder_sent = 1, reminder_date = ? WHERE due_amount > 0",
            (date.today(),)
        )
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'sent': sent_count})
    except Exception as e:
        print(f"Send bulk reminders error: {e}")
        return jsonify({'success': False})


# ==================== REPORTS ROUTES ====================
@app.route('/reports')
def reports():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        report_type = request.args.get('type', 'daily')

        conn = get_db_connection()
        cursor = conn.cursor()

        if report_type == 'daily':
            cursor.execute(
                """
                SELECT 
                    FORMAT(payment_date, 'yyyy-MM-dd') as date,
                    COUNT(*) as transactions,
                    SUM(amount) as total,
                    payment_mode
                FROM fee_payments
                WHERE payment_date = CAST(GETDATE() AS DATE)
                GROUP BY FORMAT(payment_date, 'yyyy-MM-dd'), payment_mode
                """
            )
        elif report_type == 'monthly':
            cursor.execute(
                """
                SELECT 
                    FORMAT(payment_date, 'yyyy-MM') as month,
                    COUNT(*) as transactions,
                    SUM(amount) as total
                FROM fee_payments
                WHERE payment_date >= DATEADD(month, -12, GETDATE())
                GROUP BY FORMAT(payment_date, 'yyyy-MM')
                ORDER BY month
                """
            )
        else:
            cursor.execute(
                """
                SELECT 
                    YEAR(payment_date) as year,
                    COUNT(*) as transactions,
                    SUM(amount) as total
                FROM fee_payments
                GROUP BY YEAR(payment_date)
                ORDER BY year
                """
            )

        report_data = cursor.fetchall()

        cursor.execute(
            """
            SELECT c.course_name, SUM(fp.amount) as total
            FROM fee_payments fp
            JOIN students s ON fp.student_id = s.student_id
            JOIN courses c ON s.course_id = c.id
            GROUP BY c.course_name
            ORDER BY total DESC
            """
        )
        course_wise = cursor.fetchall()

        conn.close()

        settings = get_settings()

        return render_template(
            'index.html',
            module='reports',
            role=session.get('role'),
            report_type=report_type,
            report_data=report_data,
            course_wise=course_wise,
            settings=settings,
        )
    except Exception as e:
        print(f"Reports error: {e}")
        return render_template('index.html', module='reports', role=session.get('role'), error=str(e))


@app.route('/export_report/<report_type>/<format_type>')
def export_report(report_type, format_type):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if report_type == 'daily':
            cursor.execute(
                """
                SELECT FORMAT(payment_date, 'yyyy-MM-dd') as Date,
                       s.name as Student, fp.amount as Amount,
                       fp.payment_mode as Mode, fr.receipt_no as ReceiptNo
                FROM fee_payments fp
                JOIN students s ON fp.student_id = s.student_id
                LEFT JOIN fee_receipts fr ON fp.id = fr.payment_id
                WHERE payment_date = CAST(GETDATE() AS DATE)
                """
            )
        elif report_type == 'monthly':
            cursor.execute(
                """
                SELECT FORMAT(payment_date, 'yyyy-MM') as Month,
                       COUNT(*) as Transactions,
                       SUM(amount) as Total
                FROM fee_payments
                WHERE payment_date >= DATEADD(month, -12, GETDATE())
                GROUP BY FORMAT(payment_date, 'yyyy-MM')
                """
            )
        else:
            cursor.execute(
                """
                SELECT YEAR(payment_date) as Year,
                       COUNT(*) as Transactions,
                       SUM(amount) as Total
                FROM fee_payments
                GROUP BY YEAR(payment_date)
                """
            )

        data = cursor.fetchall()
        conn.close()

        if not PANDAS_AVAILABLE:
            return "Excel export requires pandas. Please install pandas to enable Excel export.", 500

        df = pd.DataFrame([tuple(row) for row in data])

        if format_type == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=report_type.capitalize() + '_Report', index=False)
            output.seek(0)
            return send_file(output, as_attachment=True, download_name=f"{report_type}_report_{date.today()}.xlsx")

        output = df.to_csv(index=False)
        return send_file(BytesIO(output.encode()), as_attachment=True, download_name=f"{report_type}_report_{date.today()}.csv")
    except Exception as e:
        print(f"Export report error: {e}")
        return "Export failed", 500

@app.route('/advanced')
def advanced():
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin', 'accountant']:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT TOP 10 s.name, s.student_id, s.roll_no, fd.due_amount, fd.days_overdue
            FROM fee_defaulters fd
            JOIN students s ON fd.student_id = s.student_id
            WHERE fd.due_amount > 0
            ORDER BY fd.due_amount DESC
            """
        )
        top_defaulters = cursor.fetchall()

        cursor.execute(
            """
            SELECT payment_mode, ISNULL(SUM(amount), 0) as total_amount, COUNT(*) as transactions
            FROM fee_payments
            WHERE payment_date >= DATEADD(month, -6, GETDATE())
            GROUP BY payment_mode
            ORDER BY total_amount DESC
            """
        )
        payment_mode_breakdown = cursor.fetchall()

        cursor.execute(
            """
            SELECT c.course_name, COUNT(*) as enrolled_students
            FROM students s
            JOIN courses c ON s.course_id = c.id
            WHERE s.is_active = 1
            GROUP BY c.course_name
            ORDER BY enrolled_students DESC
            """
        )
        enrollment_by_course = cursor.fetchall()

        cursor.execute(
            """
            SELECT c.course_name, ISNULL(SUM(fp.amount),0) as total_collection
            FROM fee_payments fp
            JOIN students s ON fp.student_id = s.student_id
            JOIN courses c ON s.course_id = c.id
            GROUP BY c.course_name
            ORDER BY total_collection DESC
            """
        )
        collection_by_course = cursor.fetchall()

        cursor.execute("SELECT ISNULL(AVG(amount), 0) FROM fee_payments")
        avg_payment = float(cursor.fetchone()[0] or 0)

        cursor.execute("SELECT ISNULL(SUM(amount), 0) FROM fee_payments")
        total_collection = float(cursor.fetchone()[0] or 0)

        cursor.execute("SELECT COUNT(*) FROM fee_payments")
        total_transactions = cursor.fetchone()[0] or 0

        conn.close()

        return render_template(
            'index.html',
            module='advanced',
            role=session.get('role'),
            top_defaulters=top_defaulters,
            payment_mode_breakdown=payment_mode_breakdown,
            enrollment_by_course=enrollment_by_course,
            collection_by_course=collection_by_course,
            avg_payment=avg_payment,
            total_collection=total_collection,
            total_transactions=total_transactions,
        )
    except Exception as e:
        print(f"Advanced analytics error: {e}")
        return render_template('index.html', module='advanced', role=session.get('role'), error=str(e))

# ==================== EXPENSES ROUTES ====================
@app.route('/expenses')
def expenses():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, category, amount, expense_date, description, entered_by
            FROM expenses
            ORDER BY expense_date DESC
        """)
        expenses_list = cursor.fetchall()

        cursor.execute("""
            SELECT category, SUM(amount) as total
            FROM expenses
            GROUP BY category
            ORDER BY total DESC
        """)
        category_totals = cursor.fetchall()

        conn.close()

        return render_template(
            'index.html',
            module='expenses',
            role=session.get('role'),
            expenses=expenses_list,
            category_totals=category_totals,
        )
    except Exception as e:
        print(f"Expenses error: {e}")
        return render_template('index.html', module='expenses', role=session.get('role'), error=str(e))


@app.route('/add_expense', methods=['POST'])
def add_expense():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        category = request.form['category']
        amount = float(request.form['amount'])
        expense_date = request.form['expense_date']
        description = request.form.get('description', '')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO expenses (category, amount, expense_date, description, entered_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (category, amount, expense_date, description, session['user_id']),
        )
        conn.commit()
        conn.close()
        return redirect(url_for('expenses'))
    except Exception as e:
        print(f"Add expense error: {e}")
        return redirect(url_for('expenses'))

# ==================== COURSE MANAGEMENT ROUTES ====================
@app.route('/courses')
def courses():
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, course_name, course_code, duration_years, is_active FROM courses ORDER BY course_name"
        )
        courses_list = cursor.fetchall()
        conn.close()
        return render_template('index.html', module='courses', role=session.get('role'), courses=courses_list)
    except Exception as e:
        print(f"Courses error: {e}")
        return render_template('index.html', module='courses', role=session.get('role'), error=str(e))


@app.route('/add_course', methods=['POST'])
def add_course():
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return redirect(url_for('login'))

    try:
        course_name = request.form['course_name']
        course_code = request.form['course_code']
        duration_years = int(request.form['duration_years'])

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO courses (course_name, course_code, duration_years) VALUES (?, ?, ?)", (course_name, course_code, duration_years))

        cursor.execute("SELECT @@IDENTITY")
        course_id = cursor.fetchone()[0]

        for i in range(1, duration_years * 2 + 1):
            semester_name = f"Semester {i}"
            cursor.execute(
                "INSERT INTO semesters (course_id, semester_no, semester_name) VALUES (?, ?, ?)",
                (course_id, i, semester_name),
            )

        conn.commit()
        conn.close()

        return redirect(url_for('courses'))
    except Exception as e:
        print(f"Add course error: {e}")
        return redirect(url_for('courses'))


@app.route('/get_course/<int:course_id>')
def get_course(course_id):
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return jsonify({'success': False, 'error': 'Not authorized'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, course_name, course_code, duration_years, is_active FROM courses WHERE id = ?", (course_id,))
        course = cursor.fetchone()
        conn.close()

        if not course:
            return jsonify({'success': False, 'error': 'Course not found'})

        return jsonify({
            'success': True,
            'course': {
                'id': course[0],
                'course_name': course[1],
                'course_code': course[2],
                'duration_years': course[3],
                'is_active': bool(course[4]),
            }
        })
    except Exception as e:
        print(f"Get course error: {e}")
        return jsonify({'success': False, 'error': 'Failed to load course'})


@app.route('/edit_course/<int:course_id>', methods=['POST'])
def edit_course(course_id):
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return redirect(url_for('login'))

    try:
        course_name = request.form['course_name']
        course_code = request.form['course_code']
        duration_years = int(request.form['duration_years'])
        is_active = 1 if request.form.get('is_active') == '1' else 0

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE courses SET course_name = ?, course_code = ?, duration_years = ?, is_active = ? WHERE id = ?",
            (course_name, course_code, duration_years, is_active, course_id),
        )
        conn.commit()
        conn.close()
        return redirect(url_for('courses'))
    except Exception as e:
        print(f"Edit course error: {e}")
        return redirect(url_for('courses'))


# ==================== USER MANAGEMENT ROUTES ====================
@app.route('/users')
def users():
    if 'user_id' not in session or session.get('role') != 'super_admin':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, role, is_active, created_at FROM users ORDER BY created_at DESC")
        users_list = cursor.fetchall()
        conn.close()
        return render_template('index.html', module='users', role=session.get('role'), users=users_list)
    except Exception as e:
        print(f"Users error: {e}")
        return render_template('index.html', module='users', role=session.get('role'), error=str(e))


@app.route('/add_user', methods=['POST'])
def add_user():
    if 'user_id' not in session or session.get('role') != 'super_admin':
        return redirect(url_for('login'))

    try:
        username = request.form['username']
        password = hash_password(request.form['password'])
        email = request.form['email']
        role = request.form['role']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)", (username, password, email, role))
        conn.commit()
        conn.close()
        return redirect(url_for('users'))
    except Exception as e:
        print(f"Add user error: {e}")
        return redirect(url_for('users'))


@app.route('/get_user/<int:user_id>')
def get_user(user_id):
    if 'user_id' not in session or session.get('role') != 'super_admin':
        return jsonify({'success': False, 'error': 'Not authorized'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, role, is_active FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()

        if not user:
            return jsonify({'success': False, 'error': 'User not found'})

        return jsonify({
            'success': True,
            'user': {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'role': user[3],
                'is_active': bool(user[4]),
            }
        })
    except Exception as e:
        print(f"Get user error: {e}")
        return jsonify({'success': False, 'error': 'Failed to load user'})


@app.route('/edit_user/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    if 'user_id' not in session or session.get('role') != 'super_admin':
        return redirect(url_for('login'))

    try:
        username = request.form['username']
        email = request.form['email']
        role = request.form['role']
        is_active = 1 if request.form.get('is_active') == '1' else 0
        password = request.form.get('password', '').strip()

        conn = get_db_connection()
        cursor = conn.cursor()

        if password:
            cursor.execute(
                "UPDATE users SET username = ?, email = ?, role = ?, is_active = ?, password = ? WHERE id = ?",
                (username, email, role, is_active, hash_password(password), user_id),
            )
        else:
            cursor.execute(
                "UPDATE users SET username = ?, email = ?, role = ?, is_active = ? WHERE id = ?",
                (username, email, role, is_active, user_id),
            )

        conn.commit()
        conn.close()
        return redirect(url_for('users'))
    except Exception as e:
        print(f"Edit user error: {e}")
        return redirect(url_for('users'))


@app.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'super_admin':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return redirect(url_for('users'))
    except Exception as e:
        print(f"Delete user error: {e}")
        return redirect(url_for('users'))


# ==================== SETTINGS ROUTES ====================
@app.route('/settings')
def settings():
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return redirect(url_for('login'))

    settings_data = get_settings()
    return render_template('index.html', module='settings', role=session.get('role'), settings=settings_data)


@app.route('/update_setting', methods=['POST'])
def update_setting():
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        return jsonify({'success': False})

    try:
        key = request.form['key']
        value = request.form['value']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM settings WHERE setting_key = ?", (key,))
        exists = cursor.fetchone()[0] > 0

        if exists:
            cursor.execute("UPDATE settings SET setting_value = ?, updated_at = GETDATE() WHERE setting_key = ?", (value, key))
        else:
            cursor.execute("INSERT INTO settings (setting_key, setting_value) VALUES (?, ?)", (key, value))

        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Update setting error: {e}")
        return jsonify({'success': False})

# ==================== IMAGE UPLOAD & MANAGEMENT ROUTES ====================
@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    """Upload user profile image (available to all authenticated users)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    try:
        user_id = session.get('user_id')
        
        # Check if file exists in request
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        # Validate file
        if not file or not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'File type not allowed. Use: png, jpg, jpeg, gif, webp'}), 400
        
        # Generate filename with timestamp
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"user_{user_id}_{datetime.now().timestamp()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        # Save file
        file.save(filepath)
        image_path = f"/static/uploads/{filename}"
        
        # Update user profile image in database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET profile_image_path = ? WHERE id = ?", (image_path, user_id))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Image uploaded successfully',
            'image_path': image_path,
            'filename': filename
        }), 200
        
    except Exception as e:
        print(f"Image upload error: {e}")
        return jsonify({'success': False, 'error': f'Upload failed: {str(e)}'}), 500


@app.route('/api/delete_image', methods=['POST'])
def delete_image():
    """Delete user profile image"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    try:
        user_id = session.get('user_id')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current image path
        cursor.execute("SELECT profile_image_path FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            image_path = result[0]
            # Remove leading slash for file system path
            filepath = image_path.lstrip('/')
            if os.path.exists(filepath):
                os.remove(filepath)
        
        # Clear image path from database
        cursor.execute("UPDATE users SET profile_image_path = NULL WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Image deleted successfully'}), 200
        
    except Exception as e:
        print(f"Image delete error: {e}")
        return jsonify({'success': False, 'error': f'Delete failed: {str(e)}'}), 500


@app.route('/api/get_user_image')
def get_user_image():
    """Get current user's profile image path"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    try:
        user_id = session.get('user_id')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT profile_image_path FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        image_path = result[0] if result and result[0] else None
        
        return jsonify({
            'success': True,
            'image_path': image_path
        }), 200
        
    except Exception as e:
        print(f"Get image error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/profile')
def profile():
    """User profile page with image management"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        user_id = session.get('user_id')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email, role, profile_image_path, created_at FROM users WHERE id = ?",
            (user_id,)
        )
        user_data = cursor.fetchone()
        conn.close()
        
        if not user_data:
            return redirect(url_for('login'))
        
        user_info = {
            'id': user_data[0],
            'username': user_data[1],
            'email': user_data[2],
            'role': user_data[3],
            'profile_image_path': user_data[4],
            'created_at': user_data[5]
        }
        
        return render_template(
            'index.html',
            module='profile',
            role=session.get('role'),
            user_info=user_info
        )
        
    except Exception as e:
        print(f"Profile error: {e}")
        return render_template('index.html', module='profile', role=session.get('role'), error=str(e))


@app.route('/api/update_profile', methods=['POST'])
def update_profile():
    """Update user profile information"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    try:
        user_id = session.get('user_id')
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        
        if not email:
            return jsonify({'success': False, 'error': 'Email cannot be empty'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if password:
            if len(password) < 6:
                conn.close()
                return jsonify({'success': False, 'error': 'Password must be at least 6 characters'}), 400
            
            hashed_password = hash_password(password)
            cursor.execute(
                "UPDATE users SET email = ?, password = ? WHERE id = ?",
                (email, hashed_password, user_id)
            )
        else:
            cursor.execute(
                "UPDATE users SET email = ? WHERE id = ?",
                (email, user_id)
            )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Profile updated successfully'
        }), 200
        
    except Exception as e:
        print(f"Update profile error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== APPROVALS ROUTES (ADMIN ONLY) ====================

@app.route('/approvals')
def approvals():
    """Display all pending registration requests for admin approval"""
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        flash('Access denied. Admin only.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all pending registration requests
        cursor.execute("""
            SELECT id, name, email, phone, parent_name, parent_phone,
                   course_id, address, username, role, requested_at, status
            FROM registration_requests
            WHERE status = 'Pending'
            ORDER BY requested_at DESC
        """)
        pending_requests = cursor.fetchall()
        
        # Get courses for dropdown (to show course names)
        cursor.execute("SELECT id, course_name FROM courses WHERE is_active = 1")
        courses = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return render_template('index.html', 
                               module='approvals', 
                               pending_requests=pending_requests,
                               courses=courses,
                               role=session.get('role'))
    except Exception as e:
        print(f"Approvals error: {e}")
        flash('Error loading approvals page', 'error')
        return redirect(url_for('dashboard'))


@app.route('/approve_request/<int:request_id>')
def approve_request(request_id):
    """Approve a registration request and create student + user account"""
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        flash('Access denied. Admin only.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the pending request
        cursor.execute("""
            SELECT id, name, email, phone, parent_name, parent_phone, 
                   course_id, address, username, password, role
            FROM registration_requests
            WHERE id = ? AND status = 'Pending'
        """, (request_id,))
        request_data = cursor.fetchone()

        
        if not request_data:
            flash('Request not found or already processed', 'warning')
            return redirect(url_for('approvals'))
        
        # Generate student ID
        student_id = generate_student_id()
        
        role = (request_data[10] or 'student').strip().lower()

        # Insert into students table only for student role
        if role == 'student':
            cursor.execute("""
                INSERT INTO students (student_id, name, email, phone, parent_name, parent_phone,
                                     course_id, address, admission_date, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (student_id, request_data[1], request_data[2], request_data[3],
                  request_data[4], request_data[5], request_data[6], request_data[7],
                  date.today()))

        # Insert into users table (for login)
        cursor.execute("""
            INSERT INTO users (username, password, email, role, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (request_data[8], request_data[9], request_data[2], role))

        
        # Update registration request status
        cursor.execute("""
            UPDATE registration_requests 
            SET status = 'Approved', approved_by = ?, approved_at = GETDATE()
            WHERE id = ?
        """, (session['user_id'], request_id))
        
        conn.commit()
        conn.close()
        
        role_display = (role or 'student').capitalize()
        flash(f'{role_display} {request_data[1]} has been approved successfully!', 'success')
        conn.commit()
        return redirect(url_for('approvals'))
        
    except Exception as e:
        print(f"Approve request error: {e}")
        flash(f'Error approving request: {str(e)}', 'error')
        return redirect(url_for('approvals'))



@app.route('/reject_request/<int:request_id>')
def reject_request(request_id):
    """Reject a registration request"""
    if 'user_id' not in session or session.get('role') not in ['super_admin', 'admin']:
        flash('Access denied. Admin only.', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update request status to Rejected
        cursor.execute("""
            UPDATE registration_requests 
            SET status = 'Rejected', approved_by = ?, approved_at = GETDATE()
            WHERE id = ? AND status = 'Pending'
        """, (session['user_id'], request_id))
        
        conn.commit()
        conn.close()
        
        flash('Registration request has been rejected.', 'info')
        return redirect(url_for('approvals'))
        
    except Exception as e:
        print(f"Reject request error: {e}")
        flash(f'Error rejecting request: {str(e)}', 'error')
        return redirect(url_for('approvals'))


# ==================== HELPERS FOR TEMPLATE ====================
@app.context_processor
def utility_processor():
    """Make functions available to all templates"""

    def get_setting(key, default=''):
        settings = get_settings()
        return settings.get(key, default)

    return dict(get_setting=get_setting)


# ==================== MAIN ENTRY POINT ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True)

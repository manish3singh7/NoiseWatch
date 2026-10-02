import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

# Required for session cookies - set this to a random secret string
app.secret_key = "replace_this_with_a_long_random_secret_key_12345"

# --- ADMIN CREDENTIALS CONFIGURATION ---
ADMIN_USERNAME = "admin"
# Generates a secure hash of your password
ADMIN_PASSWORD_HASH = generate_password_hash("YourMasterPassword123")

DB_NAME = "noisewatch.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                location TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                db_level REAL NOT NULL,
                source TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'Open',
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()

init_db()

# Decorator to protect admin routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ----------------- ROUTES -----------------

@app.route('/')
def home():
    return render_template('index.html')

# Admin Login Page
@app.route('/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['is_admin'] = True
            return redirect(url_for('admin'))
        else:
            error = "Invalid administrator credentials."

    return render_template('login.html', error=error)

# Admin Logout
@app.route('/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

# Protected Admin Portal (Accessible only when logged in)
@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')

# Protected API to fetch citizen reports
@app.route('/api/admin/reports', methods=['GET'])
@login_required
def get_admin_reports():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                r.id, r.location, r.latitude, r.longitude, r.db_level, 
                r.source, r.description, r.status, r.timestamp,
                u.full_name, u.email, u.phone
            FROM reports r
            JOIN users u ON r.user_id = u.id
            ORDER BY r.id DESC
        ''')
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        return jsonify({'reports': result, 'count': len(result)})

# Protected API to update report status
@app.route('/api/admin/reports/<int:report_id>/status', methods=['PATCH'])
@login_required
def update_status(report_id):
    data = request.get_json()
    new_status = data.get('status')
    if new_status not in ['Open', 'Under Investigation', 'Resolved']:
        return jsonify({'error': 'Invalid status'}), 400

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE reports SET status = ? WHERE id = ?', (new_status, report_id))
        conn.commit()

    return jsonify({'status': 'success', 'message': f'Report #{report_id} status updated to {new_status}'})

# Public Citizen Report API
@app.route('/api/reports', methods=['POST'])
def submit_report():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data payload provided'}), 400

    full_name = data.get('full_name', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    location = data.get('location', '').strip()
    db_level = data.get('db_level')
    source = data.get('source', 'Other')
    description = data.get('description', '')
    coords = data.get('coordinates', [None, None])
    lat, lng = coords[0], coords[1]

    if not full_name or not phone or not location or db_level is None:
        return jsonify({'error': 'Missing required fields'}), 400

    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE phone = ? OR email = ?', (phone, email))
        user = cursor.fetchone()

        if user:
            user_id = user['id']
        else:
            cursor.execute(
                'INSERT INTO users (full_name, email, phone, created_at) VALUES (?, ?, ?, ?)',
                (full_name, email, phone, now)
            )
            user_id = cursor.lastrowid

        cursor.execute('''
            INSERT INTO reports (user_id, location, latitude, longitude, db_level, source, description, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, location, lat, lng, float(db_level), source, description, now))
        report_id = cursor.lastrowid
        conn.commit()

    return jsonify({'status': 'success', 'report_id': report_id}), 201

if __name__ == '__main__':
    app.run(debug=True, port=5000)
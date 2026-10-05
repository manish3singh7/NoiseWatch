import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# Detect if templates are inside 'templates/' or in the root folder
template_dir = os.path.abspath('templates') if os.path.isdir('templates') else os.path.abspath('.')
app = Flask(__name__, template_folder=template_dir)
CORS(app)

# Session security key
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "noisewatch_super_secure_secret_key_2026")

# --- ADMIN CREDENTIALS CONFIGURATION ---
ADMIN_USERNAME = "admin"
# Password: YourMasterPassword123
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

# ----------------- PAGE ROUTES -----------------

@app.route('/')
def home():
    return render_template('index.html')

# Admin Login Page
@app.route('/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['is_admin'] = True
            return redirect(url_for('admin'))
        else:
            error = "Invalid administrator credentials. (Hint: admin / YourMasterPassword123)"

    return render_template('login.html', error=error)

# Admin Logout
@app.route('/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

# Protected Admin Portal
@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')

# ----------------- API ROUTES -----------------

# Public: Fetch aggregate complaint count (Fixes 404 in frontend)
@app.route('/api/reports/count', methods=['GET'])
def get_reports_count():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM reports')
            row = cursor.fetchone()
            count = row['count'] if row else 0
            return jsonify({'count': count})
    except Exception as e:
        return jsonify({'count': 0, 'error': str(e)}), 500

# Public: Submit a citizen disturbance report
@app.route('/api/reports', methods=['POST'])
def submit_report():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data payload provided'}), 400

    full_name = data.get('full_name', '').strip() or 'Anonymous Citizen'
    email = data.get('email', '').strip() or 'citizen@noisewatch.org'
    phone = data.get('phone', '').strip() or 'Not Provided'
    location = data.get('location', '').strip() or 'Unspecified Location'
    db_level = data.get('db_level')
    source = data.get('source', 'Other')
    description = data.get('description', '')
    coords = data.get('coordinates', [None, None])

    lat = coords[0] if isinstance(coords, (list, tuple)) and len(coords) > 0 else None
    lng = coords[1] if isinstance(coords, (list, tuple)) and len(coords) > 1 else None

    if db_level is None:
        return jsonify({'error': 'Decibel level is required'}), 400

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    try:
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

        return jsonify({'status': 'success', 'message': 'Report successfully registered.', 'report_id': report_id}), 201
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

# Protected API: Fetch all citizen reports for admin panel
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

# Protected API: Update report status (Open -> Under Investigation -> Resolved)
@app.route('/api/admin/reports/<int:report_id>/status', methods=['PATCH'])
@login_required
def update_status(report_id):
    data = request.get_json() or {}
    new_status = data.get('status')
    if new_status not in ['Open', 'Under Investigation', 'Resolved']:
        return jsonify({'error': 'Invalid status'}), 400

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE reports SET status = ? WHERE id = ?', (new_status, report_id))
        conn.commit()

    return jsonify({'status': 'success', 'message': f'Report #{report_id} status updated to {new_status}'})

if __name__ == '__main__':
    print("==================================================")
    print("NoiseWatch Server Running at http://127.0.0.1:5000")
    print("Master Admin Credentials:")
    print("  Username: admin")
    print("  Password: YourMasterPassword123")
    print("==================================================")
    app.run(debug=True, port=5000)
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
    
# Check for Railway Persistent Volume mount or fallback to local directory
DATA_DIR = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ".")
DB_NAME = os.path.join(DATA_DIR, "noisewatch.db")
import os
import sqlite3
import math
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# 1. Base directory and template resolution
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(BASE_DIR, 'templates') if os.path.isdir(os.path.join(BASE_DIR, 'templates')) else BASE_DIR

app = Flask(__name__, template_folder=template_dir)
CORS(app)

# Session security key
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "noisewatch_super_secure_secret_key_2026")

# --- ADMIN CREDENTIALS CONFIGURATION ---
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "YourMasterPassword123")
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)

# --- DATABASE CONFIGURATION (Single Source of Truth) ---
DATA_DIR = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "noisewatch.db")

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# Haversine distance calculation in kilometers
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth's radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                base_db REAL NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                city TEXT NOT NULL
            )
        ''')

        # Seed hardware sensor stations across major urban hubs if empty
        cursor.execute('SELECT COUNT(*) as count FROM sensors')
        if cursor.fetchone()['count'] == 0:
            default_sensors = [
                # Ludhiana Cluster
                ('ldh-1', 'Clock Tower / Chaura Bazar', 30.9125, 75.8535, 89.0, 'Critical', 'Heavy Traffic & Commercial', 'Ludhiana'),
                ('ldh-2', 'Central Bus Terminal (ISBT)', 30.8986, 75.8617, 84.0, 'Critical', 'Bus Engines & Air Horns', 'Ludhiana'),
                ('ldh-3', 'Ferozepur Road / Aarti Chowk', 30.8920, 75.8235, 76.0, 'Elevated', 'Transit Congestion', 'Ludhiana'),
                ('ldh-4', 'Model Town Market', 30.8875, 75.8340, 67.0, 'Moderate', 'Commercial Activity', 'Ludhiana'),
                ('ldh-5', 'PAU Campus / Rakh Bagh', 30.9022, 75.8115, 44.0, 'Safe', 'Park / Academic Zone', 'Ludhiana'),

                # Chandigarh Cluster
                ('chd-1', 'Sector 17 Plaza / ISBT 17', 30.7415, 76.7794, 82.0, 'Critical', 'Bus Transit & Shoppers', 'Chandigarh'),
                ('chd-2', 'Tribune Chowk', 30.7055, 76.7915, 85.0, 'Critical', 'Heavy Ring Road Transit', 'Chandigarh'),
                ('chd-3', 'Sector 35 Commercial Belt', 30.7240, 76.7650, 71.0, 'Moderate', 'Food Street & Markets', 'Chandigarh'),
                ('chd-4', 'Sukhna Lake Nature Zone', 30.7421, 76.8188, 42.0, 'Safe', 'Ecology Reserve', 'Chandigarh'),

                # Delhi NCR Cluster
                ('del-1', 'Connaught Place Outer Circle', 28.6315, 77.2167, 88.0, 'Critical', 'Heavy Vehicular Hub', 'Delhi'),
                ('del-2', 'Anand Vihar ISBT Corridor', 28.6469, 77.3160, 91.0, 'Critical', 'Interstate Buses & Rail', 'Delhi'),
                ('del-3', 'Cyber City / DLF Phase 2', 28.4950, 77.0895, 78.0, 'Elevated', 'Commercial Hub Traffic', 'Delhi'),
                ('del-4', 'Lodhi Gardens Heritage Zone', 28.5933, 77.2197, 46.0, 'Safe', 'Green Enclave', 'Delhi'),

                # Mumbai Cluster
                ('mum-1', 'Dadar TT Circle Junction', 19.0178, 72.8478, 89.0, 'Critical', 'Continuous Traffic & Honking', 'Mumbai'),
                ('mum-2', 'Bandra Kurla Complex (BKC)', 19.0657, 72.8687, 75.0, 'Elevated', 'Financial District Congestion', 'Mumbai'),
                ('mum-3', 'Marine Drive Promenade', 18.9432, 72.8230, 62.0, 'Moderate', 'Coastal Traffic', 'Mumbai'),

                # Bengaluru Cluster
                ('blr-1', 'Silk Board Junction', 12.9177, 77.6238, 92.0, 'Critical', 'Heavy Transit Chokepoint', 'Bengaluru'),
                ('blr-2', 'MG Road / Brigade Chowk', 12.9756, 77.6066, 81.0, 'Critical', 'Commercial Traffic', 'Bengaluru'),
                ('blr-3', 'Cubbon Park Green Reserve', 12.9763, 77.5929, 45.0, 'Safe', 'Pedestrian Forest Zone', 'Bengaluru')
            ]
            cursor.executemany('''
                INSERT INTO sensors (station_id, label, latitude, longitude, base_db, status, source, city)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', default_sensors)

        conn.commit()

# Ensure database tables exist
init_db()

_db_ready = False
@app.before_request
def ensure_db():
    global _db_ready
    if not _db_ready:
        init_db()
        _db_ready = True

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
            error = f"Invalid administrator credentials. (Hint: {ADMIN_USERNAME} / {ADMIN_PASSWORD})"

    return render_template('login.html', error=error)

@app.route('/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')

# ----------------- API ROUTES -----------------

# Dynamic Nearby Sensor & Citizen Incident Locator API
@app.route('/api/nearby-sensors', methods=['GET'])
def get_nearby_sensors():
    try:
        lat_val = request.args.get('lat')
        lng_val = request.args.get('lng')
        radius_km = float(request.args.get('radius_km', 15.0))

        if not lat_val or not lng_val:
            return jsonify({'error': 'Latitude (lat) and Longitude (lng) query parameters are required'}), 400

        user_lat = float(lat_val)
        user_lng = float(lng_val)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid numeric coordinates or radius'}), 400

    # 1. Fetch hardware monitoring stations within radius
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT station_id, label, latitude, longitude, base_db, status, source, city 
            FROM sensors
        ''')
        all_sensors = cursor.fetchall()

    nearby_sensors = []
    for s in all_sensors:
        dist = haversine_km(user_lat, user_lng, s['latitude'], s['longitude'])
        if dist <= radius_km:
            dist_formatted = f"{int(dist * 1000)} m" if dist < 1.0 else f"{dist:.1f} km"
            nearby_sensors.append({
                'id': s['station_id'],
                'label': s['label'],
                'coords': [s['latitude'], s['longitude']],
                'baseDb': s['base_db'],
                'currentDb': s['base_db'],
                'status': s['status'],
                'source': s['source'],
                'city': s['city'],
                'distance_km': round(dist, 2),
                'distance_formatted': dist_formatted,
                'is_hardware': True
            })

    # Sort hardware sensors from nearest to farthest
    nearby_sensors.sort(key=lambda x: x['distance_km'])

    if nearby_sensors:
        return jsonify({
            'status': 'success',
            'type': 'hardware',
            'count': len(nearby_sensors),
            'radius_km': radius_km,
            'message': f"Found {len(nearby_sensors)} active station(s) within {radius_km} km.",
            'sensors': nearby_sensors
        })

    # 2. Fallback: No hardware sensors found within radius_km.
    # Query crowdsourced citizen noise reports in this radius
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT r.id, r.location, r.latitude, r.longitude, r.db_level, r.source, r.description, r.timestamp
            FROM reports r
            WHERE r.latitude IS NOT NULL AND r.longitude IS NOT NULL
            ORDER BY r.id DESC
        ''')
        reports = cursor.fetchall()

    nearby_reports = []
    for r in reports:
        dist = haversine_km(user_lat, user_lng, r['latitude'], r['longitude'])
        if dist <= radius_km:
            dist_formatted = f"{int(dist * 1000)} m" if dist < 1.0 else f"{dist:.1f} km"
            status = "Critical" if r['db_level'] >= 75 else ("Moderate" if r['db_level'] >= 60 else "Safe")
            nearby_reports.append({
                'id': f"report-{r['id']}",
                'label': r['location'] or f"Report #{r['id']}",
                'coords': [r['latitude'], r['longitude']],
                'baseDb': r['db_level'],
                'currentDb': r['db_level'],
                'status': status,
                'source': f"Citizen Log: {r['source']}",
                'distance_km': round(dist, 2),
                'distance_formatted': dist_formatted,
                'is_hardware': False,
                'timestamp': r['timestamp']
            })

    nearby_reports.sort(key=lambda x: x['distance_km'])

    if nearby_reports:
        return jsonify({
            'status': 'success',
            'type': 'crowdsourced',
            'count': len(nearby_reports),
            'radius_km': radius_km,
            'message': f"No active hardware stations within {radius_km} km. Displaying {len(nearby_reports)} recent citizen noise report(s) in your area.",
            'sensors': nearby_reports
        })

    # 3. Neither hardware stations nor citizen reports exist in that radius
    return jsonify({
        'status': 'success',
        'type': 'empty',
        'count': 0,
        'radius_km': radius_km,
        'message': f"No active stations or citizen reports found within {radius_km} km of your coordinates.",
        'sensors': []
    })

# Public: Fetch aggregate complaint count
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
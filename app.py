"""
Main Flask application
API routes and page serving
"""

from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, url_for, session, flash
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import csv
import io

import config
from database import get_db, init_db
import queue_service
import sms_service
import message_service
import message_service
import alert_service
import email_service
import uuid

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = 'supersecretkey'  # Change this to a random secret key for production

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # Check subscription status
        conn = get_db()
        user = conn.execute('SELECT subscription_status, trial_start, id FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if user:
            status, _ = check_trial_status(user)
            if status == 'expired' and request.endpoint != 'billing' and request.endpoint != 'static' and request.endpoint != 'logout':
                return redirect(url_for('billing'))

        return f(*args, **kwargs)
    return decorated_function
app.config.from_object(config)
CORS(app)

# Initialize database on first run
try:
    init_db()
    # Run migrations
    import migrate_auth
    migrate_auth.migrate()
    import migrate_trial
    migrate_trial.migrate()
    print("Database initialization and migration complete")
except Exception as e:
    print(f"Database initialization error: {e}")

# ============================================================================
# API Routes - Queue Management
# ============================================================================



@app.context_processor
def inject_office_settings():
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM offices LIMIT 1')
        row = cursor.fetchone()
        
        # Check trial status for logged in user
        trial_data = {'is_managed': False}
        if 'user_id' in session:
            user = cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            if user:
                status, days_left = check_trial_status(user)
                trial_data = {
                    'is_managed': True,
                    'status': status,
                    'days_left': days_left,
                    'show_popup': False # Can be improved to show once per session
                }

        if row:
            office = dict(row)
            # Parse theme colors
            try:
                if office.get('theme_colors'):
                    office['theme_colors'] = json.loads(office['theme_colors'])
            except:
                pass
            return dict(office_settings=office, trial=trial_data)
    except:
        pass
    return dict(office_settings={}, trial={})

def check_trial_status(user):
    """Check if trial is active or expired"""
    if user['subscription_status'] == 'active':
        return 'active', 999
        
    if user['subscription_status'] == 'expired':
        return 'expired', 0
        
    # Check if trial time has passed
    if user['trial_start']:
        try:
            start_date = datetime.strptime(user['trial_start'].split('.')[0], '%Y-%m-%d %H:%M:%S')
        except:
             # Fallback if format is different or isoformat
            start_date = datetime.fromisoformat(user['trial_start'])
            
        elapsed = datetime.now() - start_date
        if elapsed.days >= 14:
            # Expire it
            conn = get_db()
            conn.execute("UPDATE users SET subscription_status = 'expired' WHERE id = ?", (user['id'],))
            conn.commit()
            conn.close()
            return 'expired', 0
        else:
            return 'trial', 14 - elapsed.days
            
    return 'trial', 14

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        name = request.form.get('name')
        password = request.form.get('password')
        conn = get_db()
        try:
            cursor = conn.cursor()
            user_exists = cursor.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if user_exists:
                flash('Email already exists')
                conn.close()
                return redirect(url_for('signup'))
            password_hash = generate_password_hash(password)
            verification_token = str(uuid.uuid4())
            trial_start = datetime.now()
            
            cursor.execute('INSERT INTO users (email, name, password_hash, username, role, verification_token, trial_start, is_verified) VALUES (?, ?, ?, ?, ?, ?, ?, 0)',
                         (email, name, password_hash, email, 'user', verification_token, trial_start))
            conn.commit()
            conn.close()
            
            # Send verification email
            email_service.send_verification_email(email, verification_token)
            
            flash('Account created! Please check your email to verify your account.')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'An error occurred: {str(e)}')
            return redirect(url_for('signup'))
    return render_template('signup.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    try:
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE verification_token = ?', (token,)).fetchone()
        
        if not user:
            flash('Invalid verification link.')
            return redirect(url_for('login'))
            
        cursor.execute('UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?', (user['id'],))
        conn.commit()
        conn.close()
        
        flash('Email verified! You can now log in.')
        return redirect(url_for('login'))
    except Exception as e:
        flash(f'Verification failed: {str(e)}')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/billing')
@login_required
def billing():
    return render_template('billing.html', 
                         stripe_key=config.STRIPE_PUBLIC_KEY, 
                         price_id=config.STRIPE_PRICE_ID)

@app.route('/api/queue/<int:entry_id>', methods=['PATCH'])
def api_update_queue_entry(entry_id):
    """Update queue entry"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        # Update fields
        if 'notes' in data:
            cursor.execute('UPDATE queue_entries SET notes = ? WHERE id = ?', 
                         (data['notes'], entry_id))
        
        if 'quoted_wait_minutes' in data:
            cursor.execute('UPDATE queue_entries SET quoted_wait_minutes = ? WHERE id = ?', 
                         (data['quoted_wait_minutes'], entry_id))
        
        if 'waiting_outside' in data:
            queue_service.update_waiting_outside(entry_id, data['waiting_outside'])
        
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/queue/<int:entry_id>/call', methods=['POST'])
def api_call_patient(entry_id):
    """Mark patient as called in"""
    try:
        queue_service.mark_called_in(entry_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/queue/<int:entry_id>/complete', methods=['POST'])
def api_complete_queue_entry(entry_id):
    """Remove from queue (completed)"""
    try:
        queue_service.remove_from_queue(entry_id, 'completed')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/queue/<int:entry_id>/no-show', methods=['POST'])
def api_no_show(entry_id):
    """Mark as no-show"""
    try:
        queue_service.remove_from_queue(entry_id, 'no_show')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/queue/reorder', methods=['POST'])
def api_reorder_queue():
    """Reorder queue entries"""
    try:
        data = request.json
        entry_id = data['entry_id']
        new_position = data['new_position']
        
        queue_service.update_queue_position(entry_id, new_position)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# API Routes - Patients
# ============================================================================

@app.route('/api/patients', methods=['GET'])
def api_search_patients():
    """Search patients"""
    try:
        search = request.args.get('search', '')
        db = get_db()
        cursor = db.cursor()
        
        if search:
            cursor.execute('''
                SELECT 
                    p.*,
                    (SELECT MAX(checked_in_at) FROM queue_entries WHERE patient_id = p.id) as last_visit
                FROM patients p
                WHERE p.first_name LIKE ? OR p.last_name LIKE ? OR p.phone LIKE ?
                ORDER BY p.last_name, p.first_name
                LIMIT 20
            ''', (f'%{search}%', f'%{search}%', f'%{search}%'))
        else:
            cursor.execute('''
                SELECT 
                    p.*,
                    (SELECT MAX(checked_in_at) FROM queue_entries WHERE patient_id = p.id) as last_visit
                FROM patients p
                ORDER BY p.last_name, p.first_name
                LIMIT 20
            ''')
        
        patients = [dict(row) for row in cursor.fetchall()]
        db.close()
        
        return jsonify({'success': True, 'patients': patients})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



# ============================================================================
# API Routes - Check-in
# ============================================================================

@app.route('/api/checkin', methods=['POST'])
def api_checkin():
    """Check in a patient"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        # Get or create patient
        patient_id = data.get('patient_id')
        
        if not patient_id:
            # Create new patient
            cursor.execute('''
                INSERT INTO patients (first_name, last_name, phone, email)
                VALUES (?, ?, ?, ?)
            ''', (data['first_name'], data['last_name'], data['phone'], data.get('email', '')))
            patient_id = cursor.lastrowid
            db.commit()
        
        # Check if patient already in queue
        cursor.execute('''
            SELECT id FROM queue_entries 
            WHERE patient_id = ? AND status = 'waiting'
        ''', (patient_id,))
        
        if cursor.fetchone():
            db.close()
            return jsonify({'success': False, 'error': 'Patient already in queue'}), 400
        
        db.close()
        
        # Add to queue
        result = queue_service.add_to_queue(
            patient_id,
            appointment_id=data.get('appointment_id'),
            quoted_wait_minutes=data.get('quoted_wait_minutes'),
            notes=data.get('notes'),
            doctor_id=data.get('doctor_id')
        )
        
        # Get patient info for SMS
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM patients WHERE id = ?', (patient_id,))
        patient = dict(cursor.fetchone())
        db.close()
        
        # Send SMS confirmation
        patient_name = f"{patient['first_name']} {patient['last_name']}"
        sms_result = sms_service.send_checkin_confirmation(
            patient['phone'],
            patient_name,
            result['token'],
            result['position']
        )
        
        # Log notification
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO notifications (queue_entry_id, notification_type, phone_number, message, status)
            VALUES (?, 'checkin', ?, ?, ?)
        ''', (result['id'], patient['phone'], 
              f"Check-in confirmation sent to position {result['position']}", 
              sms_result['status']))
        db.commit()
        db.close()
        
        return jsonify({
            'success': True,
            'entry': result,
            'patient': patient,
            'sms_sent': sms_result['status'] in ['sent', 'mock_sent']
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# API Routes - Patient Status
# ============================================================================

@app.route('/api/status/<token>', methods=['GET'])
def api_get_status(token):
    """Get patient status by token"""
    try:
        entry = queue_service.get_queue_entry_by_token(token)
        
        if not entry:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        
        # Calculate wait time
        entry['estimated_wait_minutes'] = queue_service.calculate_wait_time(
            entry['position'],
            entry['quoted_wait_minutes']
        )
        
        # Count patients ahead
        entry['patients_ahead'] = max(0, entry['position'] - 1)
        
        return jsonify({'success': True, 'entry': entry})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/status/<token>/outside', methods=['POST'])
def api_toggle_waiting_outside(token):
    """Toggle waiting outside status"""
    try:
        entry = queue_service.get_queue_entry_by_token(token)
        if not entry:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        
        data = request.json
        waiting_outside = data.get('waiting_outside', False)
        
        queue_service.update_waiting_outside(entry['id'], waiting_outside)
        
        return jsonify({'success': True, 'waiting_outside': waiting_outside})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# API Routes - Analytics
# ============================================================================

@app.route('/api/analytics', methods=['GET'])
def api_get_analytics():
    """Get analytics data"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Average wait time
        cursor.execute('''
            SELECT AVG(
                CAST((julianday(called_in_at) - julianday(checked_in_at)) * 24 * 60 AS INTEGER)
            ) as avg_wait_minutes
            FROM queue_entries
            WHERE called_in_at IS NOT NULL AND checked_in_at IS NOT NULL
        ''')
        avg_wait = cursor.fetchone()['avg_wait_minutes'] or 0
        
        # Arrivals by hour of day
        cursor.execute('''
            SELECT 
                CAST(strftime('%H', checked_in_at) AS INTEGER) as hour,
                COUNT(*) as count
            FROM queue_entries
            GROUP BY hour
            ORDER BY hour
        ''')
        arrivals_by_hour = [dict(row) for row in cursor.fetchall()]
        
        # Arrivals by day of week (0=Sunday)
        cursor.execute('''
            SELECT 
                CAST(strftime('%w', checked_in_at) AS INTEGER) as day_of_week,
                COUNT(*) as count
            FROM queue_entries
            GROUP BY day_of_week
            ORDER BY day_of_week
        ''')
        arrivals_by_day = [dict(row) for row in cursor.fetchall()]
        
        # Quoted vs actual wait time variance
        cursor.execute('''
            SELECT 
                quoted_wait_minutes,
                CAST((julianday(called_in_at) - julianday(checked_in_at)) * 24 * 60 AS INTEGER) as actual_wait_minutes
            FROM queue_entries
            WHERE quoted_wait_minutes IS NOT NULL 
            AND called_in_at IS NOT NULL 
            AND checked_in_at IS NOT NULL
            LIMIT 100
        ''')
        wait_time_accuracy = [dict(row) for row in cursor.fetchall()]
        
        # Total patients today
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM queue_entries
            WHERE DATE(checked_in_at) = DATE('now')
        ''')
        patients_today = cursor.fetchone()['count']
        
        # Average patients per day
        cursor.execute('''
            SELECT AVG(daily_count) as avg FROM (
                SELECT DATE(checked_in_at) as date, COUNT(*) as daily_count
                FROM queue_entries
                GROUP BY date
            )
        ''')
        avg_patients_per_day = cursor.fetchone()['avg'] or 0
        
        db.close()
        
        return jsonify({
            'success': True,
            'analytics': {
                'avg_wait_minutes': round(avg_wait, 1),
                'patients_today': patients_today,
                'avg_patients_per_day': round(avg_patients_per_day, 1),
                'arrivals_by_hour': arrivals_by_hour,
                'arrivals_by_day': arrivals_by_day,
                'wait_time_accuracy': wait_time_accuracy
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



# ============================================================================
# API Routes - Alerts
# ============================================================================

@app.route('/api/alert-templates', methods=['GET'])
def api_get_alert_templates():
    """Get all alert templates"""
    try:
        templates = alert_service.get_alert_templates()
        return jsonify({'success': True, 'templates': templates})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/alert-templates', methods=['POST'])
def api_create_alert_template():
    """Create new alert template"""
    try:
        data = request.json
        template_id = alert_service.create_alert_template(
            data['name'],
            data['message_template']
        )
        return jsonify({'success': True, 'template_id': template_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/alert-templates/<int:template_id>', methods=['PATCH'])
def api_update_alert_template(template_id):
    """Update alert template"""
    try:
        data = request.json
        alert_service.update_alert_template(
            template_id,
            name=data.get('name'),
            message_template=data.get('message_template')
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/alert-templates/<int:template_id>', methods=['DELETE'])
def api_delete_alert_template(template_id):
    """Delete alert template"""
    try:
        alert_service.delete_alert_template(template_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/queue/<int:entry_id>/alert', methods=['POST'])
def api_send_alert(entry_id):
    """Send custom alert to patient"""
    try:
        data = request.json
        template_id = data.get('template_id')
        
        result = alert_service.send_custom_alert(entry_id, template_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# API Routes - Messages
# ============================================================================

@app.route('/api/messages', methods=['GET'])
def api_get_messages():
    """Get messages with optional filters"""
    try:
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        limit = int(request.args.get('limit', 100))
        
        messages = message_service.get_all_messages(limit=limit, unread_only=unread_only)
        return jsonify({'success': True, 'messages': messages})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/unread-count', methods=['GET'])
def api_get_unread_count():
    """Get count of unread messages"""
    try:
        count = message_service.get_unread_count()
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/conversations', methods=['GET'])
def api_get_conversations():
    """Get messages grouped by patient"""
    try:
        conversations = message_service.get_messages_grouped_by_patient()
        return jsonify({'success': True, 'conversations': conversations})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/patient/<int:patient_id>', methods=['GET'])
def api_get_patient_messages(patient_id):
    """Get all messages for a patient"""
    try:
        messages = message_service.get_patient_messages(patient_id)
        return jsonify({'success': True, 'messages': messages})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/mark-read', methods=['POST'])
def api_mark_messages_read():
    """Mark messages as read"""
    try:
        data = request.json
        message_ids = data.get('message_ids', [])
        message_service.mark_messages_read(message_ids)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# API Routes - Twilio Webhook
# ============================================================================

@app.route('/api/webhooks/sms', methods=['POST'])
def api_twilio_webhook():
    """Twilio inbound SMS webhook"""
    try:
        # Twilio sends form data
        from_number = request.form.get('From', request.json.get('From') if request.is_json else None)
        message_text = request.form.get('Body', request.json.get('Body') if request.is_json else None)
        
        if not from_number or not message_text:
            return jsonify({'success': False, 'error': 'Missing phone number or message'}), 400
        
        # Associate message with patient
        result = message_service.associate_message_with_patient(from_number, message_text)
        
        # Return TwiML response for Twilio
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>Thank you for your message. We'll be with you shortly!</Message>
</Response>''', 200, {'Content-Type': 'text/xml'}
        
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Enhanced queue routes to support status filtering
@app.route('/api/queue/by-status/<status>', methods=['GET'])
def api_get_queue_by_status(status):
    """Get queue entries by status (waiting, serving, completed)"""
    try:
        doctor_id = request.args.get('doctor_id')
        db = get_db()
        cursor = db.cursor()
        
        params = []
        where_clause = ""
        
        if doctor_id and doctor_id != 'undefined' and doctor_id != '':
            where_clause = " AND q.doctor_id = ?"
            params.append(doctor_id)
        
        if status == 'serving':
            # Get patients who have been called in but not yet completed
            query = f'''
                SELECT 
                    q.*,
                    p.first_name,
                    p.last_name,
                    p.phone,
                    p.email
                FROM queue_entries q
                JOIN patients p ON q.patient_id = p.id
                WHERE q.called_in_at IS NOT NULL 
                AND q.completed_at IS NULL
                AND q.status = 'waiting'
                {where_clause}
                ORDER BY q.called_in_at DESC
            '''
        elif status == 'completed':
            # Get today's completed patients
            query = f'''
                SELECT 
                    q.*,
                    p.first_name,
                    p.last_name,
                    p.phone,
                    p.email
                FROM queue_entries q
                JOIN patients p ON q.patient_id = p.id
                WHERE q.status IN ('completed', 'no_show')
                AND DATE(q.completed_at) = DATE('now')
                {where_clause}
                ORDER BY q.completed_at DESC
            '''
        else:  # waiting
            query = f'''
                SELECT 
                    q.*,
                    p.first_name,
                    p.last_name,
                    p.phone,
                    p.email
                FROM queue_entries q
                JOIN patients p ON q.patient_id = p.id
                WHERE q.status = 'waiting'
                AND q.called_in_at IS NULL
                {where_clause}
                ORDER BY q.position ASC
            '''
        
        cursor.execute(query, params)
        entries = [dict(row) for row in cursor.fetchall()]
        
        # Add estimated wait times and check for messages
        for entry in entries:
            entry['estimated_wait_minutes'] = queue_service.calculate_wait_time(
                entry.get('position', 1), 
                entry['quoted_wait_minutes']
            )
            
            # Check for unread messages from this patient
            cursor.execute('''
                SELECT COUNT(*) as count FROM messages
                WHERE queue_entry_id = ? AND direction = 'inbound' AND read = 0
            ''', (entry['id'],))
            entry['unread_messages'] = cursor.fetchone()['count']
        
        db.close()
        
        return jsonify({'success': True, 'entries': entries})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# API Routes - Patient Management & Calendar
# ============================================================================

@app.route('/api/patients', methods=['POST'])
def api_create_patient():
    """Create a new patient manually"""
    try:
        data = request.json
        required = ['first_name', 'phone']
        for field in required:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'Field {field} is required'}), 400
        
        db = get_db()
        cursor = db.cursor()
        
        # Determine phone type (default Mobile)
        phone_type = data.get('phone_type', 'Mobile')
        
        # Check for duplicates on phone or email
        cursor.execute("SELECT id FROM patients WHERE phone = ?", (data['phone'],))
        existing = cursor.fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'A patient with this phone number already exists.'}), 409
            
        if data.get('email'):
            cursor.execute("SELECT id FROM patients WHERE email = ?", (data['email'],))
            existing = cursor.fetchone()
            if existing:
                return jsonify({'success': False, 'error': 'A patient with this email already exists.'}), 409

        cursor.execute('''
            INSERT INTO patients (first_name, last_name, phone, email, phone_type, tags, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['first_name'], 
            data.get('last_name', ''), 
            data['phone'], 
            data.get('email'), 
            phone_type,
            data.get('tags'),
            'MANUAL'
        ))
        
        new_id = cursor.lastrowid
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'patient_id': new_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients/import', methods=['POST'])
def api_import_patients():
    """Import patients from CSV"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file part'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No select file'}), 400
            
        if not file.filename.endswith('.csv'):
             return jsonify({'success': False, 'error': 'File must be a CSV'}), 400

        # Read file
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        
        if not csv_input.fieldnames:
             return jsonify({'success': False, 'error': 'Empty CSV'}), 400
             
        # Normalize headers to lowercase for safer matching
        headers = [h.lower().strip() for h in csv_input.fieldnames]
        
        # Check for required columns
        if 'first_name' not in headers and 'firstname' not in headers:
             return jsonify({'success': False, 'error': 'CSV must have "first_name" column'}), 400
             
        db = get_db()
        cursor = db.cursor()
        
        stats = {
            'imported': 0,
            'skipped': 0,
            'errors': []
        }
        
        row_num = 1
        for row in csv_input:
            row_num += 1
            # Handle lenient headers
            processed_row = {k.lower().strip(): v.strip() for k, v in row.items() if k}
            
            first_name = processed_row.get('first_name') or processed_row.get('firstname')
            last_name = processed_row.get('last_name') or processed_row.get('lastname') or ''
            phone = processed_row.get('phone') or processed_row.get('mobile') or processed_row.get('cell')
            email = processed_row.get('email')
            tags = processed_row.get('tags')
            
            if not first_name or not phone:
                 stats['errors'].append(f"Row {row_num}: Missing Name or Phone")
                 continue
                 
            # Check duplicate
            cursor.execute("SELECT id FROM patients WHERE phone = ?", (phone,))
            if cursor.fetchone():
                stats['skipped'] += 1
                continue
                
            try:
                cursor.execute('''
                    INSERT INTO patients (first_name, last_name, phone, email, tags, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (first_name, last_name, phone, email, tags, 'IMPORT'))
                stats['imported'] += 1
            except Exception as e:
                stats['errors'].append(f"Row {row_num}: DB Error {str(e)}")

        db.commit()
        db.close()
        
        return jsonify({'success': True, 'stats': stats})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients/<int:patient_id>', methods=['GET'])
def api_get_patient_details(patient_id):
    """Get full patient details"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Get basic info
        cursor.execute('SELECT * FROM patients WHERE id = ?', (patient_id,))
        patient = cursor.fetchone()
        
        if not patient:
            db.close()
            return jsonify({'success': False, 'error': 'Patient not found'}), 404
            
        patient = dict(patient)
        
        # Get appointments history
        cursor.execute('''
            SELECT * FROM appointments 
            WHERE patient_id = ? 
            ORDER BY appointment_time DESC
        ''', (patient_id,))
        appointments = [dict(row) for row in cursor.fetchall()]
        
        # Get queue history
        cursor.execute('''
            SELECT * FROM queue_entries 
            WHERE patient_id = ? 
            ORDER BY checked_in_at DESC
        ''', (patient_id,))
        history = [dict(row) for row in cursor.fetchall()]
        
        # Get NOTES from dedicated table
        cursor.execute('''
            SELECT * FROM patient_notes 
            WHERE patient_id = ? 
            ORDER BY created_at DESC
        ''', (patient_id,))
        notes = [dict(row) for row in cursor.fetchall()]
        
        # Also append old queue notes if any, for legacy support
        for entry in history:
            if entry.get('notes'):
                notes.append({
                    'created_at': entry['checked_in_at'],
                    'content': f"[Queue Note] {entry['notes']}",
                    'source': 'Queue Entry'
                })
        
        # Get active queue entry ID if exists (for action buttons)
        cursor.execute('''
            SELECT id, status FROM queue_entries 
            WHERE patient_id = ? AND status IN ('waiting', 'serving')
            ORDER BY checked_in_at DESC LIMIT 1
        ''', (patient_id,))
        active_entry = cursor.fetchone()
        active_entry_id = active_entry['id'] if active_entry else None
        active_status = active_entry['status'] if active_entry else None
        
        db.close()
        
        return jsonify({
            'success': True,
            'patient': patient,
            'appointments': appointments,
            'history': history,
            'notes': notes,
            'active_queue_id': active_entry_id,
            'active_status': active_status
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients/<int:patient_id>/notes', methods=['POST'])
def api_add_patient_note(patient_id):
    """Add a note to a patient"""
    try:
        data = request.json
        if not data.get('content'):
            return jsonify({'success': False, 'error': 'Content required'}), 400
            
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            INSERT INTO patient_notes (patient_id, content)
            VALUES (?, ?)
        ''', (patient_id, data['content']))
        
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients/<int:patient_id>', methods=['PUT'])
def api_update_patient(patient_id):
    """Update patient details"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        fields = []
        values = []
        
        allowed_fields = ['first_name', 'last_name', 'phone', 'phone_type', 'email', 'tags', 'source']
        
        for field in allowed_fields:
            if field in data:
                fields.append(f"{field} = ?")
                values.append(data[field])
        
        if not fields:
            return jsonify({'success': False, 'error': 'No valid fields to update'}), 400
            
        values.append(patient_id)
        
        cursor.execute(f'''
            UPDATE patients 
            SET {', '.join(fields)}
            WHERE id = ?
        ''', values)
        
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/appointments', methods=['GET'])
def api_get_appointments():
    """Get appointments for calendar"""
    try:
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        db = get_db()
        cursor = db.cursor()
        
        # Simple query without message count - will add unread indicator later
        query = '''
            SELECT 
                a.id,
                a.patient_id,
                a.appointment_time,
                a.duration_minutes,
                a.status,
                a.notes,
                a.service,
                a.resource,
                a.created_by,
                a.confirmed,
                a.arrived,
                a.checked_in,
                a.stepping_out,
                p.first_name,
                p.last_name,
                p.phone,
                p.email,
                0 as unread_count
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
        '''
        
        params = []
        if start_date and end_date:
            query += ' WHERE a.appointment_time >= ? AND a.appointment_time <= ?'
            params = [start_date, end_date]
            
        query += ' ORDER BY a.appointment_time ASC'
        
        cursor.execute(query, params)
        appointments = [dict(row) for row in cursor.fetchall()]
        db.close()
        
        return jsonify({'success': True, 'appointments': appointments})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/appointments', methods=['POST'])
def api_create_appointment():
    """Create new appointment with patient upsert or blocking logic"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        patient_id = data.get('patient_id')
        appt_type = data.get('type', 'book') # book or block
        
        # 1. Handle Patient Upsert if 'book' type and no ID provided (or checks needed)
        if appt_type == 'book':
            # If no ID but name provided, try to find or create
            if not patient_id and data.get('name'):
                # Try finding by exact phone or email first
                # (Simple dedupe logic)
                potential_p = None
                if data.get('phone'):
                    cursor.execute("SELECT id FROM patients WHERE phone = ?", (data.get('phone'),))
                    potential_p = cursor.fetchone()
                
                if not potential_p and data.get('email'):
                    cursor.execute("SELECT id FROM patients WHERE email = ?", (data.get('email'),))
                    potential_p = cursor.fetchone()
                    
                if potential_p:
                    patient_id = potential_p['id']
                else:
                    # Create new patient
                    # Split name
                    names = data.get('name', 'Unknown').split(' ')
                    first_name = names[0]
                    last_name = ' '.join(names[1:]) if len(names) > 1 else ''
                    
                    cursor.execute('''
                        INSERT INTO patients (first_name, last_name, phone, email, tags, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        first_name, 
                        last_name, 
                        data.get('phone'), 
                        data.get('email'), 
                        data.get('tags'), 
                        datetime.now().isoformat()
                    ))
                    patient_id = cursor.lastrowid
            
            if not patient_id:
                  return jsonify({'success': False, 'error': 'Patient required for booking'}), 400

        # 2. Insert Appointment
        # If block, we might not have a patient_id. We can use NULL or a placeholder system user
        # Schema requires patient_id? Check schema.
        # implementation_plan said: "Handle 'Block' type: set status='blocked', skip patient check."
        # If schema checks FK, we might need a workaround. 
        # Assuming patient_id is NOT NULL in schema we created early on...
        # Workaround: Use existing patient or CREATE a duplicate "Blocked" patient?
        # Better: use the logic 'notes' to describe blocking if patient_id is required.
        # Or, just allow NULL in schema?
        # Let's check schema quick. If not checked, risky.
        # Assuming schema allows NULL or we just create a dummy "Blocked Slot" patient if needed.
        # Let's try nullable insert. If fails, we catch exception.
        
        status = 'scheduled'
        if appt_type == 'block':
            status = 'blocked'
            # Workaround for INNER JOIN and NOT NULL constraint: use a dummy patient
            # Check for existing "Blocked Time" patient
            cursor.execute("SELECT id FROM patients WHERE first_name = 'Blocked' AND last_name = 'Time'")
            block_p = cursor.fetchone()
            if block_p:
                patient_id = block_p['id']
            else:
                # Create one
                cursor.execute("INSERT INTO patients (first_name, last_name, phone, email, tags, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                               ('Blocked', 'Time', '000-000-0000', 'blocked@system.local', 'SYSTEM', datetime.now().isoformat()))
                patient_id = cursor.lastrowid
            
        cursor.execute('''
            INSERT INTO appointments (patient_id, appointment_time, duration_minutes, resource, service, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, 
            data['appointment_time'],
            data.get('duration', 30),
            data.get('resource'), 
            data.get('service'),
            data.get('notes'),
            status
        ))
        
        appt_id = cursor.lastrowid
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'appointment_id': appt_id})
    except Exception as e:
        return jsonify({'success': False, 'error': 'DB Error: ' + str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>', methods=['GET'])
def api_get_appointment(appointment_id):
    """Get single appointment with patient details and messages"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT 
                a.*,
                p.first_name,
                p.last_name,
                p.phone,
                p.email
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            WHERE a.id = ?
        ''', (appointment_id,))
        
        appt = cursor.fetchone()
        if not appt:
            db.close()
            return jsonify({'success': False, 'error': 'Appointment not found'}), 404
        
        appt = dict(appt)
        
        # Get messages for this patient
        cursor.execute('''
            SELECT * FROM messages 
            WHERE patient_id = ?
            ORDER BY sent_at DESC
            LIMIT 50
        ''', (appt['patient_id'],))
        messages = [dict(row) for row in cursor.fetchall()]
        
        db.close()
        return jsonify({'success': True, 'appointment': appt, 'messages': messages})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>/status', methods=['PATCH'])
def api_update_appointment_status(appointment_id):
    """Update appointment status flags (confirmed, arrived, checked_in, stepping_out)"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        allowed_fields = ['confirmed', 'arrived', 'checked_in', 'stepping_out']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = ?")
                values.append(1 if data[field] else 0)
        
        if not updates:
            return jsonify({'success': False, 'error': 'No valid fields to update'}), 400
        
        values.append(appointment_id)
        cursor.execute(f"UPDATE appointments SET {', '.join(updates)} WHERE id = ?", values)
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>/checkin', methods=['POST'])
def api_checkin_appointment(appointment_id):
    """Check in patient from appointment and add to waitlist"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Get appointment
        cursor.execute('''
            SELECT a.*, p.first_name, p.last_name, p.phone
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            WHERE a.id = ?
        ''', (appointment_id,))
        appt = cursor.fetchone()
        
        if not appt:
            db.close()
            return jsonify({'success': False, 'error': 'Appointment not found'}), 404
        
        appt = dict(appt)
        
        # Mark appointment as checked in
        cursor.execute('UPDATE appointments SET checked_in = 1 WHERE id = ?', (appointment_id,))
        
        # Check if patient already in queue
        cursor.execute('''
            SELECT id FROM queue_entries 
            WHERE patient_id = ? AND status = 'waiting'
        ''', (appt['patient_id'],))
        
        if cursor.fetchone():
            db.commit()
            db.close()
            return jsonify({'success': True, 'message': 'Already in queue'})
        
        db.commit()
        db.close()
        
        # Add to queue using queue_service
        result = queue_service.add_to_queue(
            appt['patient_id'],
            appointment_id=appointment_id,
            quoted_wait_minutes=15,
            notes=f"Checked in from appointment"
        )
        
        return jsonify({'success': True, 'queue_entry': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>/stepping-out', methods=['POST'])
def api_stepping_out(appointment_id):
    """Mark patient as stepping out - will receive reminder"""
    try:
        data = request.json
        stepping_out = data.get('stepping_out', True)
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('UPDATE appointments SET stepping_out = ? WHERE id = ?', 
                      (1 if stepping_out else 0, appointment_id))
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'stepping_out': stepping_out})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>/generate-token', methods=['POST'])
def api_generate_appointment_token(appointment_id):
    """Generate confirmation token for appointment"""
    import uuid
    try:
        token = str(uuid.uuid4())[:8]
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute('UPDATE appointments SET confirmation_token = ? WHERE id = ?', 
                      (token, appointment_id))
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'token': token})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Page Routes
# ============================================================================

@app.before_request
def handle_subdomains():
    """Handle subdomain routing for Railway deployment"""
    try:
        host = request.host.lower()
        path = request.path
        
        # Skip API, static, and existing target routes to prevent loops
        if path.startswith('/api') or path.startswith('/static') or \
           path == '/dashboard' or path == '/checkin' or path == '/display':
            return None

        # Only redirect on root path '/'
        if path == '/':
            if 'patient' in host or 'portal' in host:
                return redirect('/checkin')
            
            if 'reception' in host or 'admin' in host:
                return redirect('/dashboard')
                
            if 'waitlist' in host or 'queue' in host or 'display' in host:
                return redirect('/display')
            
    except Exception as e:
        print(f"Routing error: {e}")
        pass

@app.route('/')
def index():
    """Home page - New SaaS Landing Page"""
    return render_template('landing.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Reception dashboard"""
    return render_template('dashboard.html')

@app.route('/checkin')
def checkin():
    """Patient self check-in"""
    return render_template('checkin.html')

@app.route('/status/<token>')
def status(token):
    """Patient wait status page"""
    return render_template('status.html', token=token)

@app.route('/display')
@login_required
def display():
    """Public waiting room display"""
    return render_template('display.html')

@app.route('/messages')
@login_required
def messages():
    """Messages inbox"""
    return render_template('messages.html')

@app.route('/calendar')
@login_required
def calendar():
    """Calendar page"""
    return render_template('calendar.html')

@app.route('/customers')
@login_required
def customers():
    """Customers page"""
    return render_template('customers.html')

@app.route('/settings')
@login_required
def settings():
    """Settings page"""
    return render_template('settings.html')

@app.route('/confirm/<token>')
def confirm_appointment(token):
    """Public page for patient to confirm appointment"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT a.*, p.first_name, p.last_name
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        WHERE a.confirmation_token = ?
    ''', (token,))
    
    appt = cursor.fetchone()
    
    if not appt:
        db.close()
        return render_template('confirm_appointment.html', error=True, appointment=None)
    
    appt = dict(appt)
    
    # Check if already confirmed
    already_confirmed = appt.get('confirmed', 0) == 1
    
    # Get default form for check-in button
    cursor.execute('SELECT id FROM forms WHERE is_active=1 ORDER BY created_at DESC LIMIT 1')
    form_row = cursor.fetchone()
    default_form_id = form_row['id'] if form_row else None
    
    db.close()
    return render_template('confirm_appointment.html', 
                          error=False, 
                          appointment=appt, 
                          already_confirmed=already_confirmed,
                          token=token,
                          default_form_id=default_form_id)

@app.route('/confirm/<token>/submit', methods=['POST'])
def submit_confirmation(token):
    """Handle appointment confirmation submission"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('UPDATE appointments SET confirmed = 1 WHERE confirmation_token = ?', (token,))
    db.commit()
    db.close()
    
    return jsonify({'success': True})

@app.route('/arrived/<token>')
def arrived_page(token):
    """Public page for patient to mark arrival"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT a.*, p.first_name, p.last_name
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        WHERE a.confirmation_token = ?
    ''', (token,))
    
    appt = cursor.fetchone()
    
    if not appt:
        db.close()
        return render_template('arrived.html', error=True, appointment=None)
    
    appt = dict(appt)
    db.close()
    
    return render_template('arrived.html', 
                          error=False, 
                          appointment=appt,
                          token=token,
                          office_address=config.OFFICE_ADDRESS)

@app.route('/arrived/<token>/submit', methods=['POST'])
def submit_arrival(token):
    """Handle arrival submission"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('UPDATE appointments SET arrived = 1 WHERE confirmation_token = ?', (token,))
    db.commit()
    db.close()
    
    return jsonify({'success': True})

@app.route('/forms/<int:form_id>')
def public_form_page(form_id):
    """Public patient intake form"""
    return render_template('intake_form.html', form_id=form_id)

# ============================================================================
# API Routes - Settings & Doctors
# ============================================================================

@app.route('/api/queue', methods=['GET'])
def api_get_queue():
    try:
        doctor_id = request.args.get('doctor_id')
        db = get_db()
        cursor = db.cursor()
        
        query = "SELECT * FROM queue_entries WHERE status != 'completed' AND status != 'no_show'"
        params = []
        
        if doctor_id and doctor_id != 'undefined' and doctor_id != '':
            query += " AND doctor_id = ?"
            params.append(doctor_id)
            
        query += " ORDER BY checked_in_at"
        
        cursor.execute(query, params)
        queue = [dict(row) for row in cursor.fetchall()]
        db.close()
        return jsonify(queue)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/doctors', methods=['GET'])
def api_get_doctors():
    """Get all doctors"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM doctors WHERE active = 1 ORDER BY name')
        doctors = [dict(row) for row in cursor.fetchall()]
        db.close()
        return jsonify({'success': True, 'doctors': doctors})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/doctors', methods=['POST'])
def api_add_doctor():
    """Add a new doctor"""
    try:
        data = request.json
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Name required'}), 400
            
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO doctors (name, specialty, color, email, active)
            VALUES (?, ?, ?, ?, 1)
        ''', (data['name'], data.get('specialty'), data.get('color'), data.get('email')))
        
        doc_id = cursor.lastrowid
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'id': doc_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/doctors/<int:doctor_id>', methods=['PUT'])
def api_edit_doctor(doctor_id):
    """Edit doctor details"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        # Build update query dynamically based on provided fields
        fields = []
        params = []
        
        if 'name' in data:
            fields.append("name = ?")
            params.append(data['name'])
        if 'specialty' in data:
            fields.append("specialty = ?")
            params.append(data['specialty'])
        if 'color' in data:
            fields.append("color = ?")
            params.append(data['color'])
        if 'email' in data:
            fields.append("email = ?")
            params.append(data['email'])
            
        if not fields:
             return jsonify({'success': False, 'error': 'No fields to update'}), 400
             
        params.append(doctor_id)
        query = f"UPDATE doctors SET {', '.join(fields)} WHERE id = ?"
        
        cursor.execute(query, params)
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/doctors/<int:doctor_id>', methods=['DELETE'])
def api_delete_doctor(doctor_id):
    """Soft delete doctor"""
    try:
        db = get_db()
        cursor = db.cursor()
        # Soft delete by setting active = 0
        cursor.execute("UPDATE doctors SET active = 0 WHERE id = ?", (doctor_id,))
        db.commit()
        db.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# API Routes - Room Management
# ============================================================================

@app.route('/api/rooms', methods=['GET'])
def api_get_rooms():
    """Get all rooms with current occupants"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT * FROM rooms WHERE active = 1 ORDER BY display_order')
        rooms = [dict(row) for row in cursor.fetchall()]
        
        # Get current occupants for each room
        for room in rooms:
            cursor.execute('''
                SELECT 
                    q.*,
                    p.first_name,
                    p.last_name,
                    p.phone
                FROM queue_entries q
                JOIN patients p ON q.patient_id = p.id
                WHERE q.room_id = ? 
                AND q.status = 'serving'
                AND q.completed_at IS NULL
            ''', (room['id'],))
            occupants = [dict(row) for row in cursor.fetchall()]
            room['occupants'] = occupants
            # Backward compatibility (optional, but good for safety)
            room['occupant'] = occupants[0] if occupants else None
            
        db.close()
        return jsonify({'success': True, 'rooms': rooms})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rooms', methods=['POST'])
def api_create_room():
    """Create a new room"""
    try:
        data = request.json
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Name required'}), 400
            
        db = get_db()
        cursor = db.cursor()
        
        # Get next display order
        cursor.execute('SELECT MAX(display_order) as max_order FROM rooms')
        max_order = cursor.fetchone()['max_order'] or 0
        
        cursor.execute('''
            INSERT INTO rooms (name, display_order, active, color, opacity, doctor_id)
            VALUES (?, ?, 1, ?, ?, ?)
        ''', (
            data['name'], 
            max_order + 1,
            data.get('color'),
            data.get('opacity', 1.0),
            data.get('doctor_id')
        ))
        
        room_id = cursor.lastrowid
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'id': room_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rooms/<int:room_id>', methods=['PUT'])
def api_update_room(room_id):
    """Update room details"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        fields = []
        params = []
        
        if 'name' in data:
            fields.append("name = ?")
            params.append(data['name'])
        if 'display_order' in data:
            fields.append("display_order = ?")
            params.append(data['display_order'])
        if 'color' in data:
            fields.append("color = ?")
            params.append(data['color'])
        if 'opacity' in data:
            fields.append("opacity = ?")
            params.append(data['opacity'])
        if 'doctor_id' in data:
            fields.append("doctor_id = ?")
            params.append(data['doctor_id'])
            
        if not fields:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400
            
        params.append(room_id)
        cursor.execute(f"UPDATE rooms SET {', '.join(fields)} WHERE id = ?", params)
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rooms/<int:room_id>', methods=['DELETE'])
def api_delete_room(room_id):
    """Soft delete room"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # 1. Reset 'serving' patients back to 'waiting'
        cursor.execute('''
            UPDATE queue_entries 
            SET room_id = NULL,
                status = 'waiting',
                room_entered_at = NULL,
                called_in_at = NULL,
                vitals_taken = 0,
                dr_visited = 0,
                waiting_rx = 0,
                custom_status = NULL
            WHERE room_id = ? AND status = 'serving'
        ''', (room_id,))
        
        # 2. Unlink room from completed/other entries
        cursor.execute("UPDATE queue_entries SET room_id = NULL WHERE room_id = ?", (room_id,))
        
        # 3. Soft delete room
        cursor.execute("UPDATE rooms SET active = 0 WHERE id = ?", (room_id,))
        
        db.commit()
        db.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/queue/<int:entry_id>/assign-room', methods=['PUT'])
def api_assign_room(entry_id):
    """Assign patient to a room (from waiting -> serving)"""
    try:
        data = request.json
        room_id = data.get('room_id')
        
        db = get_db()
        cursor = db.cursor()
        
        # Check if room is already occupied
        # if room_id:
        #     cursor.execute('''
        #         SELECT id FROM queue_entries 
        #         WHERE room_id = ? AND status = 'serving' AND completed_at IS NULL
        #     ''', (room_id,))
        #     existing = cursor.fetchone()
        #     if existing:
        #         db.close()
        #         return jsonify({'success': False, 'error': 'Room is already occupied'}), 400
        
        # Update queue entry
        cursor.execute('''
            UPDATE queue_entries 
            SET room_id = ?,
                room_entered_at = ?,
                status = 'serving',
                called_in_at = COALESCE(called_in_at, ?)
            WHERE id = ?
        ''', (room_id, datetime.now().isoformat(), datetime.now().isoformat(), entry_id))
        
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/queue/<int:entry_id>/room-status', methods=['PUT'])
def api_update_room_status(entry_id):
    """Update room status flags (vitals, dr_visited, waiting_rx, custom_status)"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        fields = []
        params = []
        
        if 'vitals_taken' in data:
            fields.append("vitals_taken = ?")
            params.append(1 if data['vitals_taken'] else 0)
        if 'dr_visited' in data:
            fields.append("dr_visited = ?")
            params.append(1 if data['dr_visited'] else 0)
        if 'waiting_rx' in data:
            fields.append("waiting_rx = ?")
            params.append(1 if data['waiting_rx'] else 0)
        if 'custom_status' in data:
            fields.append("custom_status = ?")
            params.append(data['custom_status'])
            
        if not fields:
            return jsonify({'success': False, 'error': 'No status flags provided'}), 400
            
        params.append(entry_id)
        cursor.execute(f"UPDATE queue_entries SET {', '.join(fields)} WHERE id = ?", params)
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/queue/<int:entry_id>/unassign-room', methods=['PUT'])
def api_unassign_room(entry_id):
    """Remove patient from room (back to waiting or complete)"""
    try:
        data = request.json
        action = data.get('action', 'complete')  # 'waiting' or 'complete'
        
        db = get_db()
        cursor = db.cursor()
        
        if action == 'complete':
            cursor.execute('''
                UPDATE queue_entries 
                SET room_id = NULL,
                    status = 'completed',
                    completed_at = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), entry_id))
        else:
            cursor.execute('''
                UPDATE queue_entries 
                SET room_id = NULL,
                    room_entered_at = NULL,
                    status = 'waiting',
                    called_in_at = NULL,
                    vitals_taken = 0,
                    dr_visited = 0,
                    waiting_rx = 0,
                    custom_status = NULL
                WHERE id = ?
            ''', (entry_id,))
        
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# API Routes - Reminder Templates
# ============================================================================

@app.route('/api/reminder-templates', methods=['GET'])
def api_get_reminder_templates():
    """Get all reminder templates"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM reminder_templates WHERE active = 1 ORDER BY timing_minutes DESC')
        templates = [dict(row) for row in cursor.fetchall()]
        db.close()
        return jsonify({'success': True, 'templates': templates})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reminder-templates', methods=['POST'])
def api_create_reminder_template():
    """Create a new reminder template"""
    try:
        data = request.json
        if not data.get('name') or not data.get('message_template'):
            return jsonify({'success': False, 'error': 'Name and template required'}), 400
            
        name = data.get('name')
        message_template = data.get('message_template')
        form_id = data.get('form_id')
        timing_minutes = data.get('timing_minutes')
        resend_interval = data.get('resend_interval_minutes')

        # Fallback for older frontend
        if timing_minutes is None and data.get('timing_hours'):
             timing_minutes = int(data.get('timing_hours')) * 60

        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO reminder_templates (name, message_template, timing_hours, timing_minutes, resend_interval_minutes, form_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, message_template, 0, timing_minutes, resend_interval, form_id))
        
        template_id = cursor.lastrowid
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'id': template_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reminder-templates/<int:template_id>', methods=['PUT'])
def api_update_reminder_template(template_id):
    """Update reminder template"""
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        fields = []
        params = []
        
        if 'name' in data:
            fields.append("name = ?")
            params.append(data['name'])
        if 'message_template' in data:
            fields.append("message_template = ?")
            params.append(data['message_template'])
        if 'timing_hours' in data:
            fields.append("timing_hours = ?")
            params.append(data['timing_hours'])
        if 'form_id' in data:
            fields.append("form_id = ?")
            params.append(data['form_id'])
            
        if not fields:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400
            
        params.append(template_id)
        cursor.execute(f"UPDATE reminder_templates SET {', '.join(fields)} WHERE id = ?", params)
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reminder-templates/<int:template_id>', methods=['DELETE'])
def api_delete_reminder_template(template_id):
    """Soft delete reminder template"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE reminder_templates SET active = 0 WHERE id = ?", (template_id,))
        db.commit()
        db.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/appointments/<int:appointment_id>/send-reminder', methods=['POST'])
def api_send_appointment_reminder(appointment_id):
    """Send reminder for a specific appointment"""
    try:
        data = request.json
        template_id = data.get('template_id')
        custom_message = data.get('custom_message')
        
        db = get_db()
        cursor = db.cursor()
        
        # Get appointment details
        cursor.execute('''
            SELECT a.*, p.first_name, p.last_name, p.phone,
                   o.name as office_name, o.address as office_address, o.sms_from_name
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            CROSS JOIN offices o
            WHERE a.id = ?
        ''', (appointment_id,))
        appt = cursor.fetchone()
        
        if not appt:
            db.close()
            return jsonify({'success': False, 'error': 'Appointment not found'}), 404
            
        appt = dict(appt)

        # Check Phone Type
        if appt.get('phone_type') and appt.get('phone_type') != 'Mobile':
             db.close()
             return jsonify({'success': False, 'error': 'Patient phone is not Mobile. SMS skipped.'}), 400

        # Get template if specified
        message = custom_message
        if template_id and not custom_message:
            cursor.execute('SELECT message_template, form_id FROM reminder_templates WHERE id = ?', (template_id,))
            template = cursor.fetchone()
            if template:
                # Replace placeholders
                location_name = appt.get('sms_from_name') or appt.get('office_name') or "Doctor's Office"
                message = message.replace('{location_name}', location_name)
                
                message = message.replace('{patient_name}', f"{appt['first_name']} {appt['last_name']}")
                message = message.replace('{appointment_time}', appt['appointment_time'])
                
                # Calendar Link Generation
                try:
                    from datetime import datetime, timedelta
                    # Parse appointment_time (Assuming YYYY-MM-DD HH:MM:SS)
                    dt = datetime.strptime(appt['appointment_time'], '%Y-%m-%d %H:%M:%S')
                    end_dt = dt + timedelta(minutes=30) 
                    fmt = '%Y%m%dT%H%M%S'
                    dates = f"{dt.strftime(fmt)}/{end_dt.strftime(fmt)}"
                    
                    import urllib.parse
                    title = urllib.parse.quote(f"Appointment at {location_name}")
                    location = urllib.parse.quote(appt.get('office_address') or '')
                    details = urllib.parse.quote("Please arrive 10 minutes early.")
                    
                    cal_link = f"https://www.google.com/calendar/render?action=TEMPLATE&text={title}&dates={dates}&details={details}&location={location}"
                    message = message.replace('{calendar_link}', cal_link)
                except:
                    pass
                
                # Attach form link if configured
                if template['form_id']:
                    # Assuming config is imported, otherwise we import it or use app.config/current_app
                    # Note: BASE_URL is in config module, usually we imported 'import config' at top
                    import config
                    form_link = f"{config.BASE_URL}/forms/{template['form_id']}?patient_id={appt['patient_id']}"
                    message += f"\n\nComplete forms: {form_link}"
        
        if not message:
            db.close()
            return jsonify({'success': False, 'error': 'No message provided'}), 400
            
        # Send SMS (if enabled)
        # For now, just log it and mark as sent
        cursor.execute('UPDATE appointments SET reminder_sent = 1 WHERE id = ?', (appointment_id,))
        
        # Log as message
        cursor.execute('''
            INSERT INTO messages (patient_id, direction, phone_number, message_text)
            VALUES (?, 'outbound', ?, ?)
        ''', (appt['patient_id'], appt['phone'], message))
        
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'message': 'Reminder sent'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients', methods=['GET'])
def api_get_patients():
    """Get all patients for customers list"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Basic query headers
        limit = request.args.get('limit', 100)
        search = request.args.get('search', '')
        
        query = "SELECT * FROM patients WHERE 1=1"
        params = []
        
        if search:
            query += " AND (first_name LIKE ? OR last_name LIKE ? OR phone LIKE ? OR email LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s, s])
            
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        patients = [dict(row) for row in cursor.fetchall()]
        
        # Enhance with last visit info if needed?
        # For performance, maybe single query is fine for now.
        
        db.close()
        return jsonify({'success': True, 'patients': patients})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Get all settings (Office + App)"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM offices LIMIT 1')
        row = cursor.fetchone()
        office = dict(row)
        
        # Parse theme_colors if exists
        try:
            if office.get('theme_colors'):
                office['theme_colors'] = json.loads(office['theme_colors'])
        except:
             office['theme_colors'] = {}

        db.close()
        return jsonify({'success': True, 'location': office})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings', methods=['PUT'])
def api_update_settings():
    """Update settings"""
    try:
        data = request.json
        section = data.get('section')
        db = get_db()
        cursor = db.cursor()
        
        if section == 'location':
            cursor.execute('''
                UPDATE offices SET name=?, address=?, phone=?, sms_from_name=?
                WHERE id = (SELECT id FROM offices LIMIT 1)
            ''', (data.get('office_name'), data.get('address'), data.get('phone'), data.get('sms_from_name')))
            
        elif section == 'display':
            # Save theme colors
            themes = data.get('theme_colors', {})
            theme_json = json.dumps(themes)
            cursor.execute('''
                UPDATE offices SET theme_colors=?
                WHERE id = (SELECT id FROM offices LIMIT 1)
            ''', (theme_json,))
            
        db.commit()
        db.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



# ============================================================================
# Background task - Send notifications to waiting outside patients
# ============================================================================

def check_and_send_notifications():
    """Check for patients waiting outside who need notifications"""
    try:
        patients = queue_service.get_patients_needing_notification()
        
        for patient in patients:
            patient_name = f"{patient['first_name']} {patient['last_name']}"
            patients_ahead = patient['position'] - 1
            
            if patients_ahead == 0:
                # Ready now
                sms_service.send_ready_notification(patient['phone'], patient_name)
            else:
                # Almost ready
                sms_service.send_almost_ready_notification(
                    patient['phone'], 
                    patient_name, 
                    patients_ahead
                )
            
            # Mark as notified
            queue_service.mark_notified(patient['id'])
            
            # Log notification
            db = get_db()
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO notifications (queue_entry_id, notification_type, phone_number, message, status)
                VALUES (?, 'ready_soon', ?, ?, 'sent')
            ''', (patient['id'], patient['phone'], f"Notified at position {patient['position']}"))
            db.commit()
            db.close()
    except Exception as e:
        print(f"Notification error: {str(e)}")

# Simple periodic task (in production, use Celery or similar)
@app.route('/api/notifications/check', methods=['POST'])
def api_check_notifications():
    """Manual trigger for notification checking (call periodically from frontend)"""
    try:
        check_and_send_notifications()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# API Routes - Schedules
# ============================================================================

@app.route('/api/schedules', methods=['GET'])
def api_get_schedules():
    """Get all doctor schedules"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Get doctors
        cursor.execute("SELECT * FROM doctors WHERE active = 1")
        doctors = [dict(row) for row in cursor.fetchall()]
        
        # Get schedules
        cursor.execute("SELECT * FROM doctor_schedules")
        schedules_raw = [dict(row) for row in cursor.fetchall()]
        
        # Map schedules to doctors
        schedules_by_doc = {}
        for s in schedules_raw:
            did = s['doctor_id']
            if did not in schedules_by_doc:
                schedules_by_doc[did] = []
            schedules_by_doc[did].append(s)
            
        # Attach to doctors
        for d in doctors:
            d['schedule'] = schedules_by_doc.get(d['id'], [])
            
        db.close()
        return jsonify({'success': True, 'doctors': doctors})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedules', methods=['POST'])
def api_update_schedule():
    """Update a specific schedule entry"""
    try:
        data = request.json
        doctor_id = data.get('doctor_id')
        day_of_week = data.get('day_of_week')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        is_available = data.get('is_available', True)
        
        db = get_db()
        cursor = db.cursor()
        
        # Upsert
        cursor.execute('''
            INSERT INTO doctor_schedules (doctor_id, day_of_week, start_time, end_time, is_available)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(doctor_id, day_of_week) DO UPDATE SET
            start_time=excluded.start_time,
            end_time=excluded.end_time,
            is_available=excluded.is_available
        ''', (doctor_id, day_of_week, start_time, end_time, is_available))
        
        db.commit()
        db.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/schedules/blocked', methods=['GET'])
def api_get_blocked_times():
    """Get blocked times (breaks)"""
    try:
        doctor_id = request.args.get('doctor_id')
        db = get_db()
        cursor = db.cursor()
        
        if doctor_id:
            cursor.execute("SELECT * FROM doctor_blocked_times WHERE doctor_id = ?", (doctor_id,))
        else:
            cursor.execute("SELECT * FROM doctor_blocked_times")
            
        blocks = [dict(row) for row in cursor.fetchall()]
        db.close()
        return jsonify({'success': True, 'blocked_times': blocks})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedules/blocked', methods=['POST'])
def api_add_blocked_time():
    """Add a blocked time period"""
    try:
        data = request.json
        doctor_id = data.get('doctor_id')
        day_of_week = data.get('day_of_week')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        label = data.get('label', 'Break')
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO doctor_blocked_times (doctor_id, day_of_week, start_time, end_time, label)
            VALUES (?, ?, ?, ?, ?)
        ''', (doctor_id, day_of_week, start_time, end_time, label))
        
        db.commit()
        block_id = cursor.lastrowid
        db.close()
        return jsonify({'success': True, 'id': block_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedules/blocked/<int:block_id>', methods=['DELETE'])
def api_delete_blocked_time(block_id):
    """Delete a blocked time period"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM doctor_blocked_times WHERE id = ?", (block_id,))
        db.commit()
        db.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# API Routes - Patient Forms
# ============================================================================

@app.route('/api/forms', methods=['GET'])
def get_forms():
    """Get all forms"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM forms WHERE is_active=1 ORDER BY created_at DESC')
        forms = [dict(row) for row in cursor.fetchall()]
        # Parse fields JSON
        for f in forms:
            if f['fields']:
                try:
                    f['fields'] = json.loads(f['fields'])
                except:
                    f['fields'] = []
        conn.close()
        return jsonify({'success': True, 'forms': forms})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/forms', methods=['POST'])
def save_form():
    """Create or update a form"""
    try:
        data = request.json
        title = data.get('title')
        description = data.get('description') 
        fields = json.dumps(data.get('fields', []))
        form_id = data.get('id')
        
        conn = get_db()
        cursor = conn.cursor()
        
        if form_id:
            cursor.execute('''
                UPDATE forms SET title=?, description=?, fields=? WHERE id=?
            ''', (title, description, fields, form_id))
        else:
            cursor.execute('''
                INSERT INTO forms (title, description, fields) VALUES (?, ?, ?)
            ''', (title, description, fields))
            form_id = cursor.lastrowid
            
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'id': form_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/forms/<int:id>', methods=['DELETE'])
def delete_form(id):
    """Delete (archive) a form"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE forms SET is_active=0 WHERE id=?', (id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/public/forms/<int:id>', methods=['GET'])
def get_public_form(id):
    """Get public form definition"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM forms WHERE id=? AND is_active=1', (id,))
        form = cursor.fetchone()
        if not form:
            return jsonify({'success': False, 'error': 'Form not found'}), 404
            
        form = dict(form)
        if form['fields']:
            try:
                form['fields'] = json.loads(form['fields'])
            except:
                form['fields'] = []
        conn.close()
        return jsonify({'success': True, 'form': form})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/public/submissions', methods=['POST'])
def submit_form():
    """Submit a form"""
    try:
        data = request.json
        patient_id = data.get('patient_id')
        form_id = data.get('form_id')
        form_data = json.dumps(data.get('answers'))
        pdf_base64 = data.get('pdf_base64')
        
        # Save PDF to disk
        pdf_path = None
        if pdf_base64:
            import base64
            import os
            
            # Remove header if present
            if ',' in pdf_base64:
                pdf_base64 = pdf_base64.split(',')[1]
                
            pdf_bytes = base64.b64decode(pdf_base64)
            filename = f"form_{form_id}_patient_{patient_id}_{int(datetime.now().timestamp())}.pdf"
            
            # Ensure upload folder exists
            upload_dir = os.path.join(app.root_path, 'static', 'uploads', 'forms')
            os.makedirs(upload_dir, exist_ok=True)
            
            filepath = os.path.join(upload_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(pdf_bytes)
                
            pdf_path = f"/static/uploads/forms/{filename}"
            
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO patient_submissions (patient_id, form_id, form_data, pdf_path)
            VALUES (?, ?, ?, ?)
        ''', (patient_id, form_id, form_data, pdf_path))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Submission Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/patients/<int:patient_id>/submissions', methods=['GET'])
def get_patient_submissions(patient_id):
    """Get patient submissions"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT s.*, f.title as form_title 
            FROM patient_submissions s
            JOIN forms f ON s.form_id = f.id
            WHERE s.patient_id = ?
            ORDER BY s.submitted_at DESC
        ''', (patient_id,))
        subs = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'submissions': subs})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Admin / SaaS Routes
# ============================================================================

@app.route('/admin')
def admin_dashboard():
    # In production, check for session['role'] == 'admin'
    return render_template('admin.html')

@app.route('/api/admin/tenants', methods=['GET'])
def api_admin_get_tenants():
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Get offices
        cursor.execute("SELECT * FROM offices")
        offices = [dict(row) for row in cursor.fetchall()]
        
        # Get usage stats (mocked or simple counts for now)
        cursor.execute("SELECT COUNT(*) as count FROM appointments")
        total_appts = cursor.fetchone()['count']
        
        if offices:
            offices[0]['appt_count'] = total_appts
            
        # Mock SMS count (or query messages table)
        # Using a safer query if table might be empty
        try:
            cursor.execute("SELECT COUNT(*) as count FROM messages WHERE direction='outbound'")
            total_sms = cursor.fetchone()['count']
        except:
            total_sms = 0
        
        db.close()
        return jsonify({
            'success': True, 
            'tenants': offices,
            'total_sms': total_sms
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/tenants/<int:office_id>', methods=['PUT'])
def api_admin_update_tenant(office_id):
    try:
        data = request.json
        db = get_db()
        cursor = db.cursor()
        
        fields = []
        params = []
        
        if 'name' in data:
            fields.append("name = ?")
            params.append(data['name'])
        if 'plan' in data:
            fields.append("plan = ?")
            params.append(data['plan'])
        if 'theme_colors' in data:
            fields.append("theme_colors = ?")
            params.append(json.dumps(data['theme_colors']))
            
        if not fields:
            return jsonify({'success': False, 'error': 'No fields'}), 400
            
        params.append(office_id)
        cursor.execute(f"UPDATE offices SET {', '.join(fields)} WHERE id = ?", params)
        db.commit()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Run Application
# ============================================================================

if __name__ == '__main__':
    app.run(debug=config.DEBUG, host='0.0.0.0', port=5000)

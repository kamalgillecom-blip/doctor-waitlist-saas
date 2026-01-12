"""
Queue management service
Handles queue operations, position calculations, and wait time estimates
"""

from database import get_db
from datetime import datetime, timedelta
import secrets

def generate_token():
    """Generate a unique token for patient status tracking"""
    return secrets.token_urlsafe(16)

def get_queue():
    """Get all active queue entries, ordered by position"""
    db = get_db()
    cursor = db.cursor()
    
    query = '''
        SELECT 
            q.*,
            p.first_name,
            p.last_name,
            p.phone,
            p.email
        FROM queue_entries q
        JOIN patients p ON q.patient_id = p.id
        WHERE q.status = 'waiting'
        ORDER BY q.position ASC
    '''
    
    cursor.execute(query)
    entries = cursor.fetchall()
    db.close()
    
    return [dict(row) for row in entries]

def get_queue_entry_by_token(token):
    """Get queue entry by token"""
    db = get_db()
    cursor = db.cursor()
    
    query = '''
        SELECT 
            q.*,
            p.first_name,
            p.last_name,
            p.phone
        FROM queue_entries q
        JOIN patients p ON q.patient_id = p.id
        WHERE q.token = ? AND q.status = 'waiting'
    '''
    
    cursor.execute(query, (token,))
    entry = cursor.fetchone()
    db.close()
    
    return dict(entry) if entry else None

def calculate_wait_time(position, quoted_wait=None):
    """
    Calculate estimated wait time based on position
    
    Args:
        position: Position in queue (1-based)
        quoted_wait: Reception's quoted wait time in minutes
        
    Returns:
        Estimated wait time in minutes
    """
    if quoted_wait:
        return quoted_wait
    
    # Default: 15 minutes per patient before you
    base_time_per_patient = 15
    return max(0, (position - 1) * base_time_per_patient + 5)

def add_to_queue(patient_id, appointment_id=None, quoted_wait_minutes=None, notes=None, doctor_id=None):
    """
    Add patient to queue
    
    Returns:
        dict with queue entry info
    """
    db = get_db()
    cursor = db.cursor()
    
    # Get next position (global or per doctor? Usually global queue position logic applies)
    # If using per-doctor queues, might need to change this logic.
    # For now, keeping global position numbering but enabling filtering.
    cursor.execute('SELECT MAX(position) as max_pos FROM queue_entries WHERE status = "waiting"')
    result = cursor.fetchone()
    next_position = (result['max_pos'] or 0) + 1
    
    # Generate unique token
    token = generate_token()
    
    # Insert queue entry
    cursor.execute('''
        INSERT INTO queue_entries 
        (patient_id, appointment_id, position, token, quoted_wait_minutes, notes, doctor_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (patient_id, appointment_id, next_position, token, quoted_wait_minutes, notes, doctor_id))
    
    entry_id = cursor.lastrowid
    
    # Log analytics event
    cursor.execute('''
        INSERT INTO analytics_events (event_type, patient_id, queue_entry_id)
        VALUES ('check_in', ?, ?)
    ''', (patient_id, entry_id))
    
    db.commit()
    db.close()
    
    return {
        'id': entry_id,
        'position': next_position,
        'token': token,
        'estimated_wait_minutes': calculate_wait_time(next_position, quoted_wait_minutes)
    }

def update_queue_position(entry_id, new_position):
    """
    Move a queue entry to a new position
    Automatically adjusts other entries
    """
    db = get_db()
    cursor = db.cursor()
    
    # Get current position
    cursor.execute('SELECT position FROM queue_entries WHERE id = ?', (entry_id,))
    result = cursor.fetchone()
    if not result:
        db.close()
        return False
    
    old_position = result['position']
    
    if old_position == new_position:
        db.close()
        return True
    
    # Shift other entries
    if new_position < old_position:
        # Moving up - shift others down
        cursor.execute('''
            UPDATE queue_entries 
            SET position = position + 1
            WHERE position >= ? AND position < ? AND status = 'waiting' AND id != ?
        ''', (new_position, old_position, entry_id))
    else:
        # Moving down - shift others up
        cursor.execute('''
            UPDATE queue_entries 
            SET position = position - 1
            WHERE position > ? AND position <= ? AND status = 'waiting' AND id != ?
        ''', (old_position, new_position, entry_id))
    
    # Update the entry itself
    cursor.execute('''
        UPDATE queue_entries 
        SET position = ?
        WHERE id = ?
    ''', (new_position, entry_id))
    
    db.commit()
    db.close()
    
    return True

def remove_from_queue(entry_id, status='completed'):
    """
    Remove entry from queue and reposition remaining entries
    status can be: 'completed', 'no_show', 'cancelled'
    """
    db = get_db()
    cursor = db.cursor()
    
    # Get position before removing
    cursor.execute('SELECT position, patient_id FROM queue_entries WHERE id = ?', (entry_id,))
    result = cursor.fetchone()
    if not result:
        db.close()
        return False
    
    position = result['position']
    patient_id = result['patient_id']
    
    # Update status and completion time
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        UPDATE queue_entries 
        SET status = ?, completed_at = ?, called_in_at = COALESCE(called_in_at, ?)
        WHERE id = ?
    ''', (status, now, now, entry_id))
    
    # Shift remaining entries up
    cursor.execute('''
        UPDATE queue_entries 
        SET position = position - 1
        WHERE position > ? AND status = 'waiting'
    ''', (position,))
    
    # Log analytics event
    cursor.execute('''
        INSERT INTO analytics_events (event_type, patient_id, queue_entry_id)
        VALUES (?, ?, ?)
    ''', (status, patient_id, entry_id))
    
    db.commit()
    db.close()
    
    return True

def mark_called_in(entry_id):
    """Mark that patient was called in (for analytics)"""
    db = get_db()
    cursor = db.cursor()
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        UPDATE queue_entries 
        SET called_in_at = ?
        WHERE id = ?
    ''', (now, entry_id))
    
    db.commit()
    db.close()

def update_waiting_outside(entry_id, waiting_outside):
    """Update patient's waiting outside status"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        UPDATE queue_entries 
        SET waiting_outside = ?
        WHERE id = ?
    ''', (1 if waiting_outside else 0, entry_id))
    
    db.commit()
    db.close()
    
    return True

def get_patients_needing_notification():
    """
    Get patients waiting outside who should be notified
    (patients who are within notification threshold)
    """
    db = get_db()
    cursor = db.cursor()
    
    # Get notification threshold from settings
    cursor.execute('SELECT value FROM settings WHERE key = "notification_threshold_patients"')
    threshold = int(cursor.fetchone()['value'])
    
    query = '''
        SELECT 
            q.*,
            p.first_name,
            p.last_name,
            p.phone
        FROM queue_entries q
        JOIN patients p ON q.patient_id = p.id
        WHERE q.status = 'waiting' 
        AND q.waiting_outside = 1 
        AND q.outside_notified = 0
        AND q.position <= ?
    '''
    
    cursor.execute(query, (threshold,))
    entries = cursor.fetchall()
    db.close()
    
    return [dict(row) for row in entries]

def mark_notified(entry_id):
    """Mark that outside notification was sent"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        UPDATE queue_entries 
        SET outside_notified = 1
        WHERE id = ?
    ''', (entry_id,))
    
    db.commit()
    db.close()

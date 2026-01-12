"""
Message service for two-way SMS communication
Handles message storage, retrieval, and patient association
"""

from database import get_db
from datetime import datetime

def save_message(patient_id, direction, message_text, phone_number, queue_entry_id=None):
    """
    Save a message to the database
    
    Args:
        patient_id: Patient ID
        direction: 'inbound' or 'outbound'
        message_text: Message content
        phone_number: Phone number
        queue_entry_id: Optional queue entry ID
        
    Returns:
        message_id
    """
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        INSERT INTO messages (patient_id, queue_entry_id, direction, phone_number, message_text)
        VALUES (?, ?, ?, ?, ?)
    ''', (patient_id, queue_entry_id, direction, phone_number, message_text))
    
    message_id = cursor.lastrowid
    db.commit()
    db.close()
    
    return message_id

def get_patient_messages(patient_id):
    """Get all messages for a specific patient"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT * FROM messages
        WHERE patient_id = ?
        ORDER BY sent_at DESC
    ''', (patient_id,))
    
    messages = [dict(row) for row in cursor.fetchall()]
    db.close()
    
    return messages

def get_all_messages(limit=100, unread_only=False):
    """
    Get recent messages
    
    Args:
        limit: Maximum number of messages to return
        unread_only: If True, only return unread inbound messages
        
    Returns:
        List of message dicts
    """
    db = get_db()
    cursor = db.cursor()
    
    query = '''
        SELECT 
            m.*,
            p.first_name,
            p.last_name,
            p.phone
        FROM messages m
        LEFT JOIN patients p ON m.patient_id = p.id
    '''
    
    if unread_only:
        query += ' WHERE m.direction = "inbound" AND m.read = 0'
    
    query += ' ORDER BY m.sent_at DESC LIMIT ?'
    
    cursor.execute(query, (limit,))
    messages = [dict(row) for row in cursor.fetchall()]
    db.close()
    
    return messages

def get_unread_count():
    """Get count of unread inbound messages"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM messages
        WHERE direction = 'inbound' AND read = 0
    ''')
    
    count = cursor.fetchone()['count']
    db.close()
    
    return count

def mark_messages_read(message_ids):
    """Mark multiple messages as read"""
    db = get_db()
    cursor = db.cursor()
    
    placeholders = ','.join('?' * len(message_ids))
    cursor.execute(f'''
        UPDATE messages
        SET read = 1
        WHERE id IN ({placeholders})
    ''', message_ids)
    
    db.commit()
    db.close()

def find_patient_by_phone(phone_number):
    """
    Find patient by phone number
    
    Args:
        phone_number: Phone number to search (will match partial)
        
    Returns:
        Patient dict or None
    """
    db = get_db()
    cursor = db.cursor()
    
    # Clean phone number (remove non-digits)
    clean_phone = ''.join(filter(str.isdigit, phone_number))
    
    cursor.execute('''
        SELECT * FROM patients
        WHERE REPLACE(REPLACE(REPLACE(phone, '-', ''), '(', ''), ')', '') LIKE ?
        ORDER BY created_at DESC
        LIMIT 1
    ''', (f'%{clean_phone}%',))
    
    patient = cursor.fetchone()
    db.close()
    
    return dict(patient) if patient else None

def associate_message_with_patient(phone_number, message_text):
    """
    Process an inbound SMS and associate with patient
    
    Args:
        phone_number: Sender's phone number
        message_text: Message content
        
    Returns:
        dict with patient info and message_id
    """
    # Find patient
    patient = find_patient_by_phone(phone_number)
    
    if not patient:
        # Create unknown patient or log as unassociated
        patient_id = None
    else:
        patient_id = patient['id']
    
    # Find active queue entry for this patient
    queue_entry_id = None
    if patient_id:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            SELECT id FROM queue_entries
            WHERE patient_id = ? AND status = 'waiting'
            ORDER BY checked_in_at DESC
            LIMIT 1
        ''', (patient_id,))
        entry = cursor.fetchone()
        if entry:
            queue_entry_id = entry['id']
        db.close()
    
    # Save message
    message_id = save_message(
        patient_id=patient_id,
        direction='inbound',
        message_text=message_text,
        phone_number=phone_number,
        queue_entry_id=queue_entry_id
    )
    
    return {
        'message_id': message_id,
        'patient': patient,
        'patient_id': patient_id,
        'queue_entry_id': queue_entry_id
    }

def get_messages_grouped_by_patient():
    """Get messages grouped by patient for inbox view"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT 
            p.id as patient_id,
            p.first_name,
            p.last_name,
            p.phone,
            COUNT(CASE WHEN m.direction = 'inbound' AND m.read = 0 THEN 1 END) as unread_count,
            MAX(m.sent_at) as last_message_time
        FROM patients p
        INNER JOIN messages m ON p.id = m.patient_id
        GROUP BY p.id
        ORDER BY last_message_time DESC
    ''')
    
    conversations = [dict(row) for row in cursor.fetchall()]
    db.close()
    
    return conversations

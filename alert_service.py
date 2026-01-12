"""
Alert service for customizable patient notifications
Handles alert templates and message rendering
"""

from database import get_db
import sms_service
import message_service

def get_alert_templates():
    """Get all alert templates"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT * FROM alert_templates ORDER BY name')
    templates = [dict(row) for row in cursor.fetchall()]
    db.close()
    
    return templates

def get_alert_template(template_id):
    """Get a specific alert template"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT * FROM alert_templates WHERE id = ?', (template_id,))
    template = cursor.fetchone()
    db.close()
    
    return dict(template) if template else None

def create_alert_template(name, message_template):
    """Create a new alert template"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        INSERT INTO alert_templates (name, message_template)
        VALUES (?, ?)
    ''', (name, message_template))
    
    template_id = cursor.lastrowid
    db.commit()
    db.close()
    
    return template_id

def update_alert_template(template_id, name=None, message_template=None):
    """Update an existing alert template"""
    db = get_db()
    cursor = db.cursor()
    
    if name:
        cursor.execute('''
            UPDATE alert_templates SET name = ? WHERE id = ?
        ''', (name, template_id))
    
    if message_template:
        cursor.execute('''
            UPDATE alert_templates SET message_template = ? WHERE id = ?
        ''', (message_template, template_id))
    
    db.commit()
    db.close()

def delete_alert_template(template_id):
    """Delete an alert template"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('DELETE FROM alert_templates WHERE id = ?', (template_id,))
    db.commit()
    db.close()

def render_alert_message(template, patient_data):
    """
    Render an alert template with patient data
    
    Args:
        template: Template dict with 'message_template' key
        patient_data: Dict containing:
            - patient_name: Full patient name
            - position: Queue position
            - wait_time: Estimated wait time string (e.g., "15 min")
            
    Returns:
        Rendered message string
    """
    message = template['message_template']
    
    # Replace placeholders
    message = message.replace('{patient_name}', patient_data.get('patient_name', ''))
    message = message.replace('{position}', str(patient_data.get('position', '')))
    message = message.replace('{wait_time}', patient_data.get('wait_time', ''))
    
    return message

def send_custom_alert(queue_entry_id, template_id):
    """
    Send a custom alert to a patient
    
    Args:
        queue_entry_id: Queue entry ID
        template_id: Alert template ID
        
    Returns:
        dict with success status and message_id
    """
    # Get queue entry with patient info
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT 
            q.*,
            p.first_name,
            p.last_name,
            p.phone
        FROM queue_entries q
        JOIN patients p ON q.patient_id = p.id
        WHERE q.id = ?
    ''', (queue_entry_id,))
    
    entry = cursor.fetchone()
    db.close()
    
    if not entry:
        return {'success': False, 'error': 'Queue entry not found'}
    
    entry = dict(entry)
    
    # Get template
    template = get_alert_template(template_id)
    if not template:
        return {'success': False, 'error': 'Template not found'}
    
    # Calculate wait time
    from queue_service import calculate_wait_time
    wait_minutes = calculate_wait_time(entry['position'], entry['quoted_wait_minutes'])
    
    # Format wait time
    if wait_minutes < 60:
        wait_time_str = f"{wait_minutes} min"
    else:
        hours = wait_minutes // 60
        mins = wait_minutes % 60
        wait_time_str = f"{hours}h {mins}m"
    
    # Prepare patient data
    patient_data = {
        'patient_name': f"{entry['first_name']} {entry['last_name']}",
        'position': entry['position'],
        'wait_time': wait_time_str
    }
    
    # Render message
    message = render_alert_message(template, patient_data)
    
    # Send SMS
    sms_result = sms_service.send_sms(entry['phone'], message)
    
    # Log message
    if sms_result['status'] in ['sent', 'mock_sent']:
        message_id = message_service.save_message(
            patient_id=entry['patient_id'],
            direction='outbound',
            message_text=message,
            phone_number=entry['phone'],
            queue_entry_id=queue_entry_id
        )
        
        # Also log in notifications table
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO notifications (queue_entry_id, notification_type, phone_number, message, status)
            VALUES (?, 'custom_alert', ?, ?, ?)
        ''', (queue_entry_id, entry['phone'], message, sms_result['status']))
        db.commit()
        db.close()
        
        return {
            'success': True,
            'message_id': message_id,
            'sms_status': sms_result['status']
        }
    else:
        return {
            'success': False,
            'error': sms_result.get('error', 'Failed to send SMS')
        }

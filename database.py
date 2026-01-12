"""
Database initialization and helper functions
"""

import sqlite3
from datetime import datetime
import config

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with schema"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Offices table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS offices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT,
            phone TEXT,
            settings TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Users table (reception/admin)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            office_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (office_id) REFERENCES offices (id)
        )
    ''')
    
    # Patients table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Appointments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            appointment_time TIMESTAMP NOT NULL,
            duration_minutes INTEGER DEFAULT 30,
            status TEXT DEFAULT 'scheduled',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients (id)
        )
    ''')
    
    # Queue entries table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS queue_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            appointment_id INTEGER,
            position INTEGER NOT NULL,
            status TEXT DEFAULT 'waiting',
            checked_in_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            called_in_at TIMESTAMP,
            completed_at TIMESTAMP,
            quoted_wait_minutes INTEGER,
            waiting_outside BOOLEAN DEFAULT 0,
            outside_notified BOOLEAN DEFAULT 0,
            token TEXT UNIQUE NOT NULL,
            notes TEXT,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            FOREIGN KEY (appointment_id) REFERENCES appointments (id)
        )
    ''')
    
    # Analytics events table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            patient_id INTEGER,
            queue_entry_id INTEGER,
            event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            FOREIGN KEY (queue_entry_id) REFERENCES queue_entries (id)
        )
    ''')
    
    # Notifications table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_entry_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            message TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'sent',
            FOREIGN KEY (queue_entry_id) REFERENCES queue_entries (id)
        )
    ''')
    
    # Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Messages table - for two-way SMS communication
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            queue_entry_id INTEGER,
            direction TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            message_text TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            read BOOLEAN DEFAULT 0,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            FOREIGN KEY (queue_entry_id) REFERENCES queue_entries (id)
        )
    ''')
    
    # Alert templates table - customizable alert messages
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alert_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            message_template TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Add columns to appointments table if they don't exist
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN color TEXT')
    except:
        pass  # Column already exists
    
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN reminder_sent BOOLEAN DEFAULT 0')
    except:
        pass  # Column already exists
    
    
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN reminder_sent BOOLEAN DEFAULT 0')
    except:
        pass  # Column already exists

    # Phase 3 Enhancements
    try:
        cursor.execute('ALTER TABLE patients ADD COLUMN tags TEXT')
    except:
        pass

    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN source TEXT DEFAULT 'WEB-APP'")
    except:
        pass

    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN resource TEXT')
    except:
        pass

    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN service TEXT')
    except:
        pass

    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN created_by INTEGER')
    except:
        pass
    
    # Phase 7: Appointment Status Tracking (Calendar Enhancements)
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN confirmed BOOLEAN DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN arrived BOOLEAN DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN checked_in BOOLEAN DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN stepping_out BOOLEAN DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN confirmation_token TEXT')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN reminder_24hr_sent BOOLEAN DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE appointments ADD COLUMN reminder_1hr_sent BOOLEAN DEFAULT 0')
    except:
        pass
    
    # Phase 4: Patient Notes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patient_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients (id)
        )
    ''')

    # Phase 8: Patient Forms
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            fields TEXT,  -- JSON string of form fields
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patient_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            form_id INTEGER NOT NULL,
            form_data TEXT,  -- JSON string of answers
            pdf_path TEXT,   -- Path to generated PDF file
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            FOREIGN KEY (form_id) REFERENCES forms (id)
        )
    ''')

    # Phase 5: Multi-Provider Support
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            specialty TEXT,
            color TEXT,
            email TEXT,
            active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Doctor Schedules (Weekly)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctor_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL, -- 0=Monday, 6=Sunday
            start_time TEXT, -- HH:MM (24h)
            end_time TEXT, -- HH:MM (24h)
            is_available BOOLEAN DEFAULT 1,
            FOREIGN KEY (doctor_id) REFERENCES doctors (id),
            UNIQUE(doctor_id, day_of_week)
        )
    ''')

    try:
        cursor.execute('ALTER TABLE queue_entries ADD COLUMN doctor_id INTEGER')
    except:
        pass

    # Phase 6: Room Management
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT 1,
            color TEXT,
            opacity REAL DEFAULT 1.0,
            doctor_id INTEGER
        )
    ''')

    try:
        cursor.execute("ALTER TABLE rooms ADD COLUMN color TEXT")
    except:
        pass
        
    try:
        cursor.execute("ALTER TABLE rooms ADD COLUMN opacity REAL DEFAULT 1.0")
    except:
        pass
        
    try:
        cursor.execute("ALTER TABLE rooms ADD COLUMN doctor_id INTEGER")
    except:
        pass
    
    # Room tracking columns for queue_entries
    try:
        cursor.execute('ALTER TABLE queue_entries ADD COLUMN room_id INTEGER')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE queue_entries ADD COLUMN room_entered_at TIMESTAMP')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE queue_entries ADD COLUMN vitals_taken BOOLEAN DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE queue_entries ADD COLUMN dr_visited BOOLEAN DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE queue_entries ADD COLUMN waiting_rx BOOLEAN DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE queue_entries ADD COLUMN custom_status TEXT')
    except:
        pass
    
    # Reminder templates for appointments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminder_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            message_template TEXT NOT NULL,
            timing_hours INTEGER DEFAULT 24,
            active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    try:
        cursor.execute('ALTER TABLE reminder_templates ADD COLUMN form_id INTEGER')
    except:
        pass
    
    # Insert default rooms if none exist
    cursor.execute('SELECT COUNT(*) as count FROM rooms')
    if cursor.fetchone()['count'] == 0:
        default_rooms = [
            ('Room 1', 1),
            ('Room 2', 2),
            ('Room 3', 3),
            ('Room 4', 4),
        ]
        for name, order in default_rooms:
            cursor.execute('INSERT INTO rooms (name, display_order) VALUES (?, ?)', (name, order))
    
    # Insert default reminder templates if none exist
    cursor.execute('SELECT COUNT(*) as count FROM reminder_templates')
    if cursor.fetchone()['count'] == 0:
        default_reminders = [
            ('24 Hour Reminder', 'Hi {patient_name}, this is a reminder about your appointment tomorrow at {appointment_time}. Reply CONFIRM to confirm or call us to reschedule.', 24),
            ('2 Hour Reminder', 'Hi {patient_name}, your appointment is in 2 hours at {appointment_time}. Please arrive 10 minutes early. Reply if you need to reschedule.', 2),
        ]
        for name, template, hours in default_reminders:
            cursor.execute('INSERT INTO reminder_templates (name, message_template, timing_hours) VALUES (?, ?, ?)', (name, template, hours))
    
    # Insert default office
    cursor.execute('SELECT COUNT(*) as count FROM offices')
    if cursor.fetchone()['count'] == 0:
        cursor.execute('''
            INSERT INTO offices (name, address, phone)
            VALUES (?, ?, ?)
        ''', (config.OFFICE_NAME, config.OFFICE_ADDRESS, config.OFFICE_PHONE))
        
    try:
        cursor.execute('ALTER TABLE offices ADD COLUMN sms_from_name TEXT')
    except:
        pass
        
    # Patient Phone Type
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN phone_type TEXT DEFAULT 'Mobile'")
    except:
        pass

    # Reminder Timing Enhancements
    try:
        cursor.execute("ALTER TABLE reminder_templates ADD COLUMN timing_minutes INTEGER")
        cursor.execute("ALTER TABLE reminder_templates ADD COLUMN resend_interval_minutes INTEGER")
        
        # Migrate existing hours to minutes
        cursor.execute("UPDATE reminder_templates SET timing_minutes = timing_hours * 60 WHERE timing_minutes IS NULL")
    except:
        pass
    
    # Insert default admin user (password: admin123)
    cursor.execute('SELECT COUNT(*) as count FROM users')
    if cursor.fetchone()['count'] == 0:
        # Simple password hash for demo (use proper hashing in production)
        cursor.execute('''
            INSERT INTO users (username, password_hash, role, office_id)
            VALUES (?, ?, ?, ?)
        ''', ('admin', 'admin123', 'admin', 1))
    
    # Insert default settings
    default_settings = [
        ('notification_threshold_patients', '2'),
        ('default_wait_time_minutes', '15'),
        ('auto_refresh_seconds', '30'),
        ('sms_enabled', 'false')
    ]
    
    for key, value in default_settings:
        cursor.execute('''
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
        ''', (key, value))
    
    # Insert default alert templates
    cursor.execute('SELECT COUNT(*) as count FROM alert_templates')
    if cursor.fetchone()['count'] == 0:
        default_templates = [
            ('Standard Alert', 'Hi {patient_name}, you are currently #{position} in line. Estimated wait time: {wait_time}. Dr. Smith\'s Office'),
            ('Ready Soon', 'Hi {patient_name}, you\'re almost up! Only {position} patient(s) ahead. Please be ready. Dr. Smith\'s Office'),
            ('Custom Reminder', 'Hi {patient_name}, this is a reminder about your visit today. Current position: #{position}. Dr. Smith\'s Office')
        ]
        
        for name, template in default_templates:
            cursor.execute('''
                INSERT INTO alert_templates (name, message_template)
                VALUES (?, ?)
            ''', (name, template))
    
    
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == '__main__':
    init_db()

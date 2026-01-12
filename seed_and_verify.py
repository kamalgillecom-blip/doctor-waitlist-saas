
import sqlite3
import datetime

def seed_data():
    conn = sqlite3.connect('waitlist.db')
    cursor = conn.cursor()
    
    # 1. Create a patient if not exists
    cursor.execute("INSERT OR IGNORE INTO patients (id, first_name, last_name, phone, email, tags, source) VALUES (99, 'Test', 'Patient', '555-0199', 'test@example.com', 'VIP', 'Manual')")
    
    # 2. Create an appointment for TODAY (2026-01-01) at 10 AM
    # "Today" in the simulation context is 2026-01-01
    today_str = "2026-01-01"
    appt_time = f"{today_str}T10:00:00"
    
    cursor.execute('''
        INSERT INTO appointments (patient_id, appointment_time, duration_minutes, resource, service, status, notes)
        VALUES (99, ?, 60, 'Dock 1', 'Checkup', 'scheduled', 'Initial consultation')
    ''', (appt_time,))
    
    conn.commit()
    conn.close()
    print("Seeded appointment for 2026-01-01 10:00 AM")

if __name__ == '__main__':
    seed_data()

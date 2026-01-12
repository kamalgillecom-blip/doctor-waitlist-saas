"""
SMS notification service
Supports both Twilio production mode and mock development mode
"""

import config
from datetime import datetime

if config.SMS_ENABLED:
    from twilio.rest import Client
    client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
else:
    client = None

def send_sms(to_phone, message):
    """
    Send SMS message
    
    Args:
        to_phone: Recipient phone number
        message: Message text
        
    Returns:
        dict with status and message_id
    """
    if config.SMS_ENABLED and client:
        try:
            msg = client.messages.create(
                body=message,
                from_=config.TWILIO_PHONE_NUMBER,
                to=to_phone
            )
            return {
                'status': 'sent',
                'message_id': msg.sid,
                'error': None
            }
        except Exception as e:
            print(f"SMS Error: {str(e)}")
            return {
                'status': 'failed',
                'message_id': None,
                'error': str(e)
            }
    else:
        # Mock mode - just log to console
        print(f"\n{'='*60}")
        print(f"📱 MOCK SMS")
        print(f"{'='*60}")
        print(f"To: {to_phone}")
        print(f"Message: {message}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        return {
            'status': 'mock_sent',
            'message_id': f'mock_{datetime.now().timestamp()}',
            'error': None
        }

def send_checkin_confirmation(phone, patient_name, token, position):
    """Send check-in confirmation with status link"""
    link = f"{config.BASE_URL}/status/{token}"
    message = f"Hi {patient_name}, you've been checked in at {config.OFFICE_NAME}. You are #{position} in line. Track your wait time: {link}"
    return send_sms(phone, message)

def send_ready_notification(phone, patient_name):
    """Send notification that patient should come in"""
    message = f"Hi {patient_name}, please come in now. {config.OFFICE_NAME} is ready to see you."
    return send_sms(phone, message)

def send_almost_ready_notification(phone, patient_name, patients_ahead):
    """Send notification that patient's turn is coming up"""
    message = f"Hi {patient_name}, you're almost up! {patients_ahead} patient(s) ahead of you at {config.OFFICE_NAME}. Please be ready."
    return send_sms(phone, message)

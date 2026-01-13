"""
Configuration file for the waitlist application
"""

import os

# Flask configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
DEBUG = True

# Database
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'waitlist.db'))

# SMS Configuration (Twilio)
SMS_ENABLED = os.environ.get('SMS_ENABLED', 'False').lower() == 'true'
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '')

# Application Settings
DEFAULT_WAIT_TIME_MINUTES = 15
NOTIFICATION_THRESHOLD_PATIENTS = 2  # Notify when this many patients ahead
BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')

# Email Configuration (SMTP)
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', 'noreply@doctorwaitlist.com')

# Stripe Configuration
STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY', '')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID', 'price_H5ggYJDqKS') # Replace with actual

# Office Settings
OFFICE_NAME = "Dr. Smith's Office"
OFFICE_ADDRESS = "123 Medical Plaza, Suite 100"
OFFICE_PHONE = "(555) 123-4567"

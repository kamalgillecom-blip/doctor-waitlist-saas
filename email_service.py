
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import config

def send_email_async(to_email, subject, html_content):
    """Send email asynchronously to avoid blocking"""
    thread = threading.Thread(target=send_email_sync, args=(to_email, subject, html_content))
    thread.start()

def send_email_sync(to_email, subject, html_content):
    """Send email via SMTP"""
    if not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
        print(f"Skipping email to {to_email} (No credentials)")
        # For development, you might want to log the email content
        print(f"Subject: {subject}")
        print(f"Content: {html_content[:100]}...")
        return

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = config.SMTP_FROM_EMAIL
        msg['To'] = to_email

        part = MIMEText(html_content, 'html')
        msg.attach(part)

        # Standard SMTP connection
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_FROM_EMAIL, to_email, msg.as_string())
            
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")

def send_verification_email(to_email, token):
    """Send verification email with link"""
    verify_url = f"{config.BASE_URL}/verify-email/{token}"
    html_content = f"""
    <h2>Welcome to {config.OFFICE_NAME}!</h2>
    <p>Please click the link below to verify your email address:</p>
    <p><a href="{verify_url}" style="padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">Verify Email</a></p>
    <p>Or verify using this link: {verify_url}</p>
    <p>Your 14-day free trial starts now!</p>
    """
    send_email_async(to_email, "Verify your email address", html_content)

# Doctor's Office Waitlist Management SaaS

A comprehensive web-based waitlist management system designed specifically for doctor's offices.

## Features

- **Patient Check-in**: Self-service and reception check-in
- **Queue Management**: Drag-and-drop queue reordering
- **SMS Notifications**: Automated wait time updates
- **Waiting Outside Mode**: Notify patients when it's almost their turn
- **Analytics Dashboard**: Track wait times, arrival patterns, and efficiency metrics
- **Public Display**: TV/monitor display for waiting rooms
- **Appointment Calendar**: Integrated appointment scheduling

## Tech Stack

- **Backend**: Python/Flask
- **Database**: SQLite
- **Frontend**: Vanilla HTML, CSS, JavaScript
- **SMS**: Twilio (mock mode included for development)

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:
   ```bash
   python app.py
   ```

3. Open your browser to:
   - Reception Dashboard: http://localhost:5000/dashboard
   - Patient Check-in: http://localhost:5000/checkin
   - Public Display: http://localhost:5000/display

## Default Login

- Username: `admin`
- Password: `admin123` (change in production!)

## SMS Configuration

To enable real SMS notifications, add your Twilio credentials to `config.py`:
- Account SID
- Auth Token
- Phone Number

For development, the app runs in mock SMS mode and logs messages to the console.

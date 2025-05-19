# Tickets - E-Ticketing System

A comprehensive e-ticketing system for attractions and events, enabling online ticket purchasing, QR code validation, and administrative management.

## System Overview

Tickets is a full-stack web application that provides:
- Online ticket purchase for various attractions
- QR code-based e-tickets delivery via email
- Real-time ticket validation for entry control
- Administrative dashboard for managing attractions and viewing stats

## Architecture

- **Frontend**: HTML/CSS/JavaScript with Tailwind CSS
  - Consumer portal for ticket purchasing
  - Admin interface for attraction management
  - Validator app for scanning and validating tickets
  - Multi-language support

- **Backend**: Python Flask RESTful API
  - PostgreSQL database for data persistence
  - Email service for ticket delivery
  - QR code generation and validation

## Features

- **For Visitors**:
  - Browse available attractions
  - Purchase tickets with different types (full price, discount, free)
  - Receive e-tickets via email with QR codes
  - Mobile-friendly interface

- **For Administrators**:
  - Manage attractions (add, edit, delete)
  - View sales statistics and reports
  - User authentication and authorization

- **For Validators**:
  - Scan QR codes using mobile camera
  - Instant ticket validation
  - Visual and audio feedback for validation results

## Setup and Installation

### Requirements
- Python 3.8+
- PostgreSQL database
- SMTP server for email delivery

### Backend Setup
1. Navigate to the backend directory:
   ```
   cd tickets/backend
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   - `DATABASE_URL`: PostgreSQL connection string
   - `FLASK_SECRET_KEY`: Secret key for session management
   - `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`: Email server configuration

4. Configure `.env` file with your PostgreSQl and SMTP:
   ```
   DATABASE_URL=postgresql://postgres:your_password@localhost:5432/ict4gs
   SECRET_KEY=ict4gs
   DEFAULT_LANGUAGE=en

   MAIL_SERVER=
   MAIL_PORT=
   MAIL_USE_TLS=True
   MAIL_USE_SSL=False
   MAIL_USERNAME=
   MAIL_PASSWORD=
   MAIL_DEFAULT_SENDER=
   ```

5. Start the Flask server:
   ```
   python app.py
   ```

6. (Optional) Reset the database:
   ```
   python reset_db.py
   ```

### Frontend Access
- Consumer Portal: Open `frontend/consumer.html` in a web browser
- Admin Interface: Open `frontend/admin.html` in a web browser
- Validator App: Open `frontend/validator.html` in a web browser (preferably on a mobile device)
- You should use `localhost:5000/*.html` to visit the website instead of directly open

## Usage

1. **As an Administrator**:
   - Log in to the admin interface
   - Add attractions with details and pricing
   - View sales reports and statistics

2. **As a Customer**:
   - Browse available attractions
   - Select desired date and ticket quantities
   - Complete purchase to receive tickets via email

3. **As a Validator**:
   - Open the validator app on a mobile device
   - Scan customer's QR code
   - Verify ticket validity for entry permission

## License

This project is provided as open-source software.



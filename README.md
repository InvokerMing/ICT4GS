# ICT4GS_Group_14

ICT4GS_Group_14 is a project that consists of two main subsystems: a monitoring system and a ticketing system. It is designed to provide real-time monitoring and ticket management functionalities, potentially for event or access control scenarios.

## Project Structure

```
ICT4GS/
│
├── monitor/
│   ├── main.py           # Main script for the monitoring system
│   ├── requirements.txt  # Python dependencies for monitoring system
│   └── yolov11s.pt       # YOLOv1 model weights for object detection
│
└── tickets/
    ├── backend/
    │   ├── app.py            # Backend server for ticket management
    │   ├── requirements.txt  # Python dependencies for backend
    │   └── reset_db.py       # Script to reset the ticket database
    │
    └── frontend/
        ├── consumer.html     # Frontend for consumers
        ├── validator.html    # Frontend for validators
        ├── admin.html        # Frontend for administrators
        ├── languages/        # Language files for localization
        └── res/              # Static resources (images, etc.)
```

## Monitor System

- Located in the `monitor/` directory.
- Uses a YOLOv11-based model (`yolov11s.pt`) for real-time object detection.
- Main entry point: `main.py`.

## Ticket System

- Located in the `tickets/` directory.
- **Backend**: Python-based server (Flask), handles ticket validation, issuance, and admin operations.
- **Frontend**: HTML files for different user roles (consumer, validator, admin), with support for multiple languages and static resources.

## Installation

### Prerequisites

- Python 3.8+
- CUDA-compatible GPU (recommended) or CPU
- PostgreSQL database
- SMTP server for email delivery
  
### Backend Setup

```bash
cd tickets/backend
pip install -r requirements.txt
python app.py
```

### Monitor Setup

```bash
cd monitor
pip install -r requirements.txt
python main.py
```

### Frontend

- Open the relevant HTML file in `tickets/frontend/` in your browser with `localhost:5000/*.html` and opened backend:
  - `consumer.html` for ticket holders
  - `validator.html` for ticket checkers
  - `admin.html` for administrators

## Notes

- The monitoring system may require a webcam or video input device.
- The ticketing backend may require a database; see `reset_db.py` for initialization.
- For more details, refer to the code and comments in each module.


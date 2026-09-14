# FAATN-GATE — Website & System Architecture

**Gateway for Artisans and Technical Experts**  
Connecting Skills · Innovation · Opportunities · Nation Development

> Developer Study Copy (Confidential) — built from the official architecture diagram.

---

## Features Implemented

### Public Website
- Modern **3D-inspired glassmorphism** design with animated background
- Hero section with floating 3D cards
- GATE Entry Point (9 user pathways)
- Vision / Mission / Impact
- Functional Modules overview
- Responsive navigation

### Registration & Classification (Routing Engine)
- Full registration form capturing:
  - Identity (name, email, phone)
  - Location (State → LGA → Community)
  - Occupation / Specialty
  - Skills & Experience
  - Needs / Opportunities
- Role selection (Artisan, Technician, Engineer, Institution, Government, Industry, Innovation, Opportunity, Partner)

### Artisan / Technician Dashboard
- **My Profile** — edit identity, location, skills, portfolio
- **Training** — browse & enroll in trainings (skill-gap → certification route)
- **Opportunities** — view matched jobs/contracts/grants & apply
- **Innovation** — submit ideas and track Innovation Route stages
- **Messages** — inbox from matching engine & coordinators
- **Notifications** — system alerts
- Stats overview cards

### Admin Portal
- User management overview
- Counts for members, opportunities, innovations

### Backend
- **Python Flask** application
- **SQLAlchemy** + **SQLite** database
- **Flask-Login** authentication
- Password hashing (Werkzeug)
- Seeded demo data

---

## Demo Login Credentials

| Role        | Email              | Password          |
|-------------|--------------------|-------------------|
| Artisan     | artisan@demo.ng    | Artisan@123       |
| Technician  | tech@demo.ng       | Tech@123          |
| Admin       | admin@faatn.ng     | Admin@FAATN2026   |

---

## How to Run

```bash
cd faatn_gate
pip install -r requirements.txt
python app.py
```

Then open: **http://127.0.0.1:5000**

---

## Project Structure

```
faatn_gate/
├── app.py                 # Flask app, models, routes, seed data
├── requirements.txt
├── README.md
├── static/
│   └── css/style.css      # 3D glassmorphism design system
└── templates/
    ├── base.html
    ├── index.html
    ├── about.html
    ├── gate.html
    ├── register.html
    ├── login.html
    ├── dashboard_base.html
    ├── dashboard_artisan.html
    ├── dashboard_admin.html
    ├── profile.html
    ├── trainings.html
    ├── opportunities.html
    ├── innovations.html
    ├── messages.html
    └── notifications.html
```

---

## Architecture Mapping (from diagram)

1. **Public FAATN Website** → Home, About, GATE Entry pages  
2. **FAATN-GATE Entry Point** → 9 pathway cards → Registration  
3. **Registration & Classification** → Full form + role routing  
4. **GATE Database** → User, Training, Innovation, Opportunity, Message, Notification models  
5. **Functional Modules** → Training, Innovation, Opportunities, Matching logic  
6. **User Dashboards** → Role-based (Artisan/Technician fully built)  
7. **Innovation Route** → Idea submission + status tracking  
8. **Training Route** → Enroll → status (enrolled / completed / certified)  
9. **Opportunity Route** → Apply → application status  

---

## Next Steps (Production)

- Switch SQLite → PostgreSQL
- Add file upload for portfolio / documents
- Real matching engine (location + skill scoring)
- Email notifications
- Multi-role dashboards (Engineer, Institution, Industry…)
- Phased rollout flags (Phase 1–4)

---

**FAATN-GATE: PEOPLE → SKILLS → INNOVATION → OPPORTUNITIES → IMPACT**  
*Harnessing Nigeria’s Artisans and Technical Talent for a Greater Tomorrow*

# FAATN-GATE — Gateway for Artisans & Technical Experts

**Connecting Skills · Innovation · Opportunities · Nation Development**

Official digital gateway of the Federation of Artisans and Technicians of Nigeria (FAATN).

---

## Design System (keep these colours)

| Token            | Hex       | Role                          |
|------------------|-----------|-------------------------------|
| Primary Green    | `#0d7a4f` | Brand, CTAs, headers          |
| Primary Dark     | `#065f3c` | Hover / pressed states        |
| Primary Light    | `#16a34a` | Accents                       |
| Secondary Blue   | `#1d4ed8` | Links, secondary actions      |
| Accent Teal      | `#0d9488` | Theme colour, highlights      |
| Nigeria Green    | `#15803d` | National identity accents     |

Glassmorphism cards, soft shadows, Inter font, and the rotating workshop background imagery are core to the look — do not replace them with a flat redesign.

---

## Features

### Public site
- Hero with floating 3D cards and animated background slides
- GATE entry point (role pathways)
- About, Contact, Events/News, Gallery
- Find artisans/technicians, Find suppliers, Need Help, Institutions

### Member area (after login)
- Profile, Trainings, Opportunities, Innovations
- Messages / Chat, Notifications
- Directory (admin listing controls)

### Admin
- User overview, listing categories, basic metrics

### Backend
- Flask + SQLAlchemy
- SQLite for local preview (automatic when `DATABASE_URL` is unset)
- PostgreSQL for production (`DATABASE_URL=postgresql://...`)
- Flask-Login + Werkzeug password hashing
- Seeded demo accounts

---

## Demo logins

| Role        | Email              | Password        |
|-------------|--------------------|-----------------|
| Artisan     | artisan@demo.ng    | Artisan@123     |
| Technician  | tech@demo.ng       | Tech@123        |
| Admin       | admin@faatn.ng     | Admin@FAATN2026 |

---

## How to run (local)

```bash
cd faatn_gate_clean
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open: **http://127.0.0.1:5000**

Optional environment variables:

```bash
export SECRET_KEY="your-production-secret"
export DATABASE_URL="postgresql://user:pass@host:5432/faatn_gate"
export PORT=5000
export FLASK_DEBUG=1
```

---

## Project structure (cleaned)

```
faatn_gate_clean/
├── app.py                 # Models, routes, seed data
├── requirements.txt
├── README.md
├── startup.sh             # Optional process helper
├── static/
│   ├── css/style.css      # Design system (glass + 3D)
│   ├── images/
│   │   ├── logo/
│   │   ├── backgrounds/
│   │   └── leadership/
│   └── uploads/           # avatars, chat, events, gallery
└── templates/             # Jinja2 pages (extends base.html)
```

---

## Design notes for future improvements

Keep the existing colour palette and glass/3D language. Suggested non-breaking upgrades:

1. **Performance** – compress background JPGs and serve WebP where supported.
2. **Accessibility** – ensure all floating cards and nav links keep visible focus rings (already partially present).
3. **Mobile** – the CSS already has solid breakpoints; test the hamburger menu on real devices.
4. **Content** – replace placeholder leadership photos and event copy with real FAATN assets when available.
5. **SEO** – JSON-LD and Open Graph tags are already in `base.html`; keep them updated per page.

Do **not** replace the green/teal/blue system or the glass card style with a generic Bootstrap/Tailwind default theme.

---

## Production notes

- Set a strong `SECRET_KEY`.
- Use PostgreSQL via `DATABASE_URL`.
- Run behind Gunicorn: `gunicorn -b 0.0.0.0:5000 app:app`
- Configure uploads folder persistence (avatars, gallery, events).

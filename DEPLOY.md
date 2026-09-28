# Deploy FAATN-GATE

The app is Flask + PostgreSQL. Recommended host: **Render** (free tier works for testing).

---

## Option A — Render (recommended)

### 1. Push code to GitHub
1. Create a new GitHub repository (public or private).
2. Upload the `faatn_gate_clean` folder contents as the repo root  
   (so `app.py` and `requirements.txt` are at the top level).

```bash
cd faatn_gate_clean
git init
git add .
git commit -m "FAATN-GATE ready to deploy"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/faatn-gate.git
git push -u origin main
```

### 2. Create services on Render
1. Go to [https://render.com](https://render.com) → Sign up / Log in.
2. **New → Blueprint** → connect your GitHub repo  
   OR create manually:

**PostgreSQL**
- New → PostgreSQL  
- Name: `faatn-gate-db`  
- Plan: Free  

**Web Service**
- New → Web Service → select the repo  
- Runtime: **Python 3**  
- Build command: `pip install -r requirements.txt`  
- Start command:  
  `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`

### 3. Environment variables (Web Service → Environment)
| Key | Value |
|-----|--------|
| `DATABASE_URL` | Copy **Internal Database URL** from the Postgres service |
| `SECRET_KEY` | Any long random string (Render can auto-generate) |
| `FLASK_DEBUG` | `0` |

> If Render gives `postgres://...`, the app converts it to `postgresql://` automatically.

### 4. Deploy
Click **Create Web Service**. Wait for the build to finish.  
Open the URL Render gives you (e.g. `https://faatn-gate.onrender.com`).

### 5. Demo logins (after first deploy)
| Role | Email | Password |
|------|--------|----------|
| Artisan | artisan@demo.ng | Artisan@123 |
| Technician | tech@demo.ng | Tech@123 |
| Admin | admin@faatn.ng | Admin@FAATN2026 |

---

## Option B — Railway

1. Go to [https://railway.app](https://railway.app) → New Project → Deploy from GitHub.
2. Add a **PostgreSQL** plugin.
3. Set variables:
   - `DATABASE_URL` = Railway Postgres URL  
   - `SECRET_KEY` = random string  
4. Start command:  
   `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`

---

## Option C — PythonAnywhere / VPS

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://user:pass@host:5432/faatn_gate"
export SECRET_KEY="change-me"
gunicorn app:app --bind 0.0.0.0:8000
```

Put Nginx in front and point a domain to the server.

---

## Important notes

1. **Uploads (product photos, avatars)** are stored on the server disk.  
   On free Render/Railway, the disk can reset on redeploy. For production, use S3 or Cloudflare R2 later.

2. **Change demo passwords** after go-live, or delete demo users from Admin.

3. Set a strong **SECRET_KEY** in production.

4. First request after idle may be slow on free tiers (cold start).

---

## Local production-style test

```bash
cd faatn_gate_clean
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="local-test-secret"
export DATABASE_URL="sqlite:///./faatn_gate.db"   # or real Postgres
gunicorn app:app --bind 0.0.0.0:5000
```

# FAATN-GATE — Corrected files summary

## What was fixed / added

1. **Admin credentials hidden**
   - Removed Demo Accounts box from `templates/login.html`
   - Removed Demo logins table from `README.md`
   - Admin password now comes from env vars `ADMIN_EMAIL` / `ADMIN_PASSWORD`

2. **Messages go to recipient inbox**
   - New `deliver_to_inbox()` helper in `app.py`
   - Peer chat → Message + Notification in recipient inbox
   - Admin broadcast → Message + Notification in each recipient inbox
   - Inbox page shows full system/admin messages

3. **Admin Send Notification**
   - New route `/dashboard/admin/send-notification`
   - New template `templates/admin_send_notification.html`
   - Link on Admin Dashboard
   - Keyword filter (e.g. `massage`) for occupation/specialty/skills/needs

4. **Occupations**
   - Added: Massage Therapist, Spa / Wellness Therapist, Beauty Therapist

5. **Public profile**
   - Logged-in users get **Message (inbox)** button

## Files in this package

- `app.py` — full corrected backend
- `README.md` — credentials removed
- `requirements.txt`
- `templates/` — all pages (corrected ones overlaid)
- `static/css/style.css` — design system CSS

## Still needed from original RAR

Copy these from your original project (images not included here to keep size small):

- `static/images/` (logo, backgrounds, leadership)
- `static/uploads/` folders (avatars, chat, events, gallery, products)

## Deploy

```bash
# Set private admin first
export ADMIN_EMAIL="you@example.com"
export ADMIN_PASSWORD="YourStrongPassword"

# Copy static images from original FAATN folder, then:
python app.py
# or production:
gunicorn -b 0.0.0.0:5000 app:app
```


## SEO / Favicon update

- `app.py`: Google + Bing verification settings (env vars or edit the constants near the top), `/sitemap.xml`, improved `/robots.txt`, `/favicon.ico`, `/site.webmanifest`, optional `/googleXXXX.html` and `/BingSiteAuth.xml` file verification
- `templates/base.html`: verification meta tags (only output once a real code is set), favicon include
- `templates/dashboard_base.html`: favicon + `noindex` for private dashboard pages
- `templates/_favicon.html`: favicon links (SVG, ICO, PNG, Apple touch icon, manifest)
- `static/favicon/`: favicon set (replace with your real logo icons if you like, keep the file names)

### How to add your verification codes
Render > Environment, add:
  GOOGLE_SITE_VERIFICATION = <content value from Google Search Console>
  BING_SITE_VERIFICATION   = <content value from Bing Webmaster Tools>
  PUBLIC_SITE_URL          = https://yourdomain.ng
Then redeploy, and click Verify in each console. Submit https://yourdomain.ng/sitemap.xml in both.


## Keyword / SEO update (trade + location pages)

- `templates/base.html`: title suffix is now `| FAATN-GATE`; canonical and og:url use `PUBLIC_SITE_URL` and drop query strings
- Page-specific `<title>` and meta description on Home, Find, Marketplace, Market Hub, Suppliers, About, Contact, Gate, Events, Gallery, Institutions, Need Help
- `app.py`: `SEO_TRADES` and `SEO_LOCATIONS` tables + `/<slug>` route, giving pages like `/electricians-in-abuja` and `/solar-installers-in-lagos`
- `templates/seo_landing.html`: unique `<h1>`, intro, member cards (no phone numbers), trade-specific FAQs with FAQPage + Breadcrumb JSON-LD, internal links
- Landing pages with no listed members are `noindex` and left out of `sitemap.xml` until someone is listed
- `templates/index.html`: "Popular searches" internal links
- To add a trade or city, edit the two dictionaries near `seo_landing` in `app.py`

---

## Merge update (admin screens, hardening, update emails)

- **Admin screens added** (the routes existed but the pages did not): Add a user, Reset password, Delete, and a Trash page (`admin_trash.html`, previously a crash). Sidebar link to Trash.
- **No default admin password.** `seed_data()` needs `ADMIN_PASSWORD`; `flask create-admin` added; max 2 admins everywhere. `admin@faatn.ng` is auto-removed only if it still uses a public password and another admin exists.
- **Passwords are never emailed.** New users get a set-your-password link; admin "set password" sends only a "password changed" notice; an admin cannot set another admin's password.
- **Forgot-password** throttled (1 email / 5 min per account) and a "password changed" notice is sent after every reset.
- **Update emails** respect an opt-out (`user.email_notifications`, profile checkbox, unsubscribe link + List-Unsubscribe header): profile-visit emails, admin broadcasts, and a new "email this to members" checkbox when publishing Events / News.
- **Help form**: one-time confirmation to the visitor (capped per address) and optional admin alert (`ADMIN_NOTIFY_EMAIL`).
- **Brevo API** added next to Resend and SMTP. Admin dashboard shows email status and a "Send a test email" button.
- Schema: `ensure_schema_updates()` adds `user.email_notifications` automatically (SQLite and PostgreSQL).
- Added `static/favicon/favicon.ico`.
- **Change password** card on the Profile page (any signed-in user), and a red warning on the Admin page while the admin password is a publicly known default.
- Local `.env` (git-ignored) creates the first admin on first start. Replace the starting password straight away.
- **Sitemap**: now also lists `/find/suppliers`, `/market-hub`, `/institutions`, `/need-help` and every active marketplace listing; URLs are XML-escaped; `robots.txt` hides `/email/unsubscribe/`.
- Homepage `<title>` typo fixed (it read "Artisans,& and Technicians").
- `MAIL_REPLY_TO` setting (Reply-To header on all three email transports); `PUBLIC_SITE_URL` set to https://faatn-gate.com in `render.yaml` and `.env.example`.

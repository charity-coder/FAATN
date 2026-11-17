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


## Email verification, visitor alerts, demo data removed

- `app.py`: SMTP / Resend email helper (background thread); registration and "Resend verification" now email the verification link instead of showing it on the page
- `app.py`: `notify_profile_visit()` — when someone opens `/member/<id>` the member gets an in-app notification (type `visit`) and an email (max one email per hour; bots, the owner and repeat refreshes within an hour are ignored)
- `app.py`: demo users (artisan@/tech@/engineer@demo.ng) and their sample messages/notifications are no longer seeded; `remove_demo_data()` deletes them (and all their related rows) from existing databases at startup
- `app.py`: seed guard now checks for any admin account, not a hard-coded `admin@faatn.ng`
- `templates/notifications.html`: icon for visit notifications
- `DEPLOY.md`: demo logins and the published admin password removed; mail settings documented
- `app.py`: password reset link is now emailed (`send_reset_email`) instead of being shown on the page; the same message is shown whether or not the email is registered


## Admin: notify any registered user, delete users and their data

- `app.py` `admin_send_notification`: send to one specific user (`?user_id=`) or to a group (all registered users, or one role: artisan, technician, engineer, institution, government, industry, partner, supplier), optional keyword filter, optional "also send by email". Admin accounts are never targeted.
- `app.py` `admin_delete_user` (POST `/dashboard/admin/user/<id>/delete`): admin only; cannot delete yourself or another admin. Deleting now moves the user to **Trash** (see below).
- `app.py` `purge_users()`: removes the user's profile, enrolments, innovations, applications, notifications, messages (sent and received), reviews, marketplace listings, help requests (by account or email) and the uploaded files (avatar, chat images, product photos). Events/gallery items they created are kept, just unlinked. `remove_demo_data()` now uses it too.
- `templates/dashboard_admin.html`: search box, "Notify" and "Delete" (with confirmation) buttons per user.
- `templates/admin_send_notification.html`: audience selector, single-user mode, email checkbox.

## Trash with permanent-delete approval

- New table `TrashedUser`: JSON copy of the user, their enrolments, innovations, applications, notifications, messages, products (+photos), reviews and help requests. Uploaded files are copied to a `trash/<id>/` folder **outside** `static/` (never publicly reachable; override with `TRASH_FOLDER`).
- `trash_user()` runs on Delete: copies to Trash, then removes the user from the live site (they vanish from the directory, cannot log in, their email is freed).
- `/dashboard/admin/trash`: list with **Restore** and **Delete permanently** (the approval step; erases the copy and files).
- `restore_user()`: recreates the account and data. Refuses if the email has since been taken; skips messages/reviews whose other party no longer exists.
- Demo-account cleanup (`remove_demo_data`) still deletes straight away, without Trash.
- Trash is on the server disk, so on hosts with an ephemeral disk set `TRASH_FOLDER` to a persistent volume.

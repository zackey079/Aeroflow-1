AEROFLOW — MULTI-USER PRIVATE ACCOUNT VERSION

FEATURES
- Self-service account registration and sign-in
- Passwords stored as secure Werkzeug password hashes
- Each user has private flights, pilots, and aircraft
- User-scoped reads, updates, and deletes
- Flight pilot/aircraft references validated against the signed-in user's own records
- SQLite WAL mode and busy timeout for concurrent access
- Existing page templates and styling retained

LOCAL WINDOWS SETUP
1. Install Python 3.10 or newer.
2. Open Command Prompt in this folder.
3. Create and activate a virtual environment:
   python -m venv venv
   venv\Scripts\activate
4. Install packages:
   pip install -r requirements.txt
5. Set a strong secret key (keep it private):
   set SECRET_KEY=replace-with-a-long-random-secret
6. Start the website:
   python app.py
7. Open http://127.0.0.1:5000 and register a separate account for each user.

DEPLOYMENT
- Start command: gunicorn app:app
- Set SECRET_KEY to a long random value in the hosting provider's environment settings.
- Set DATABASE_PATH to a persistent disk path if the host's filesystem is ephemeral.
- Set COOKIE_SECURE=1 when serving the site over HTTPS.
- Do not run multiple application instances against SQLite on ephemeral/local disks. For larger production deployments, migrate to PostgreSQL.
- Use HTTPS and configure backups for the persistent database.

DATABASE MIGRATION
The app automatically adds user_id columns to a legacy AeroFlow SQLite database. Existing records without an owner are deliberately not shown to newly registered accounts, to prevent accidental data exposure. If you need to preserve legacy records, assign them to a specific trusted account through a controlled migration before making the site public.

SECURITY NOTE
This version adds account authentication and data ownership enforcement. Before public production use, add CSRF protection (e.g. Flask-WTF), rate limiting, email-based password recovery, and operational monitoring. Do not use the development server for production hosting.


ADMIN USER ACTIVITY REPORT
- The app records successful logins, registrations, logouts, and create/update/delete
  actions for flights, pilots, and aircraft in the activity_logs database table.
- Tracking starts when this updated version is installed; actions from before that
  time cannot be reconstructed from the existing database.
- To grant the report page to one administrator, set ADMIN_USERNAME to the exact
  username of that account (case-insensitive match).
- Windows Command Prompt example:
    set ADMIN_USERNAME=your_admin_username
    set SECRET_KEY=use-a-long-random-secret
    py app.py
- Render: add ADMIN_USERNAME and SECRET_KEY under Dashboard > Environment.
- Sign in using that administrator account. A "User Activity Report" link appears.
- The page is /admin/activity. Use "Export Excel report" to download
  AeroFlow_User_Activity_Report.xlsx. The workbook has Activity Log and User Summary
  sheets. The Activity Log contains the complete event history.
- Do not make ADMIN_USERNAME a public value in your UI. Only the configured admin
  username can access the all-user activity report.
- Install requirements after this update:
    py -m pip install -r requirements.txt

import os, sqlite3, uuid
from io import BytesIO
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = Path(BASE_DIR) / "aeroflow.db"
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

# Required for Flask sessions. Set SECRET_KEY in the hosting environment for deployment.
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "aeroflow-local-development-key-change-before-deployment"
)

# Keep all flight status labels in one place for forms and the dashboard.
STATUSES = ["Scheduled", "Assigned", "In Air", "Delayed", "Completed", "Cancelled"]

print("========== AEROFLOW DEBUG ==========")
print("App location:", BASE_DIR)
print("Templates folder exists:", os.path.isdir(TEMPLATE_DIR))
print("Auth file exists:", os.path.isfile(
    os.path.join(TEMPLATE_DIR, "auth.html")
))

if os.path.isdir(TEMPLATE_DIR):
    print("Template files:", os.listdir(TEMPLATE_DIR))

print("===================================")
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=30000')
    return con

def init_db():
    with db() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pilots (
          id TEXT PRIMARY KEY, user_id TEXT, pilot_code TEXT NOT NULL,
          name TEXT NOT NULL, rank TEXT NOT NULL DEFAULT 'Captain', license_number TEXT,
          flight_hours INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          UNIQUE(user_id,pilot_code)
        );
        CREATE TABLE IF NOT EXISTS aircraft (
          id TEXT PRIMARY KEY, user_id TEXT, registration TEXT NOT NULL,
          model TEXT NOT NULL, capacity INTEGER NOT NULL DEFAULT 180,
          status TEXT NOT NULL DEFAULT 'Active', created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          UNIQUE(user_id,registration)
        );
        CREATE TABLE IF NOT EXISTS flights (
          id TEXT PRIMARY KEY, user_id TEXT, flight_number TEXT NOT NULL,
          origin TEXT NOT NULL, destination TEXT NOT NULL, departure_time TEXT NOT NULL,
          arrival_time TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Scheduled',
          aircraft_id TEXT, pilot_id TEXT, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY(aircraft_id) REFERENCES aircraft(id) ON DELETE SET NULL,
          FOREIGN KEY(pilot_id) REFERENCES pilots(id) ON DELETE SET NULL,
          UNIQUE(user_id,flight_number)
        );
        CREATE TABLE IF NOT EXISTS activity_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id TEXT,
          username TEXT NOT NULL,
          action TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          entity_id TEXT,
          details TEXT,
          occurred_at TEXT NOT NULL
        );
        ''')
        # Safe in-place migration for databases created by the original single-user app.
        for table in ('pilots','aircraft','flights'):
            cols={r['name'] for r in con.execute(f'PRAGMA table_info({table})')}
            if 'user_id' not in cols:
                con.execute(f'ALTER TABLE {table} ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE')
        con.execute('CREATE INDEX IF NOT EXISTS idx_flights_user_departure ON flights(user_id,departure_time)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_pilots_user_code ON pilots(user_id,pilot_code)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_aircraft_user_reg ON aircraft(user_id,registration)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_logs(occurred_at)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_logs(user_id,occurred_at)')

def now_iso(): return datetime.now().isoformat(timespec='seconds')

def add_activity(con, user_id, username, action, entity_type='account', entity_id=None, details=''):
    """Append one audit event. Never store passwords or other credentials here."""
    con.execute(
        'INSERT INTO activity_logs(user_id,username,action,entity_type,entity_id,details,occurred_at) VALUES(?,?,?,?,?,?,?)',
        (user_id, username, action, entity_type, entity_id, details, now_iso())
    )

def current_user_is_admin():
    configured_admin = os.environ.get('ADMIN_USERNAME', '').strip()
    return bool(configured_admin and getattr(g, 'user', None)
                and g.user['username'].casefold() == configured_admin.casefold())

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user_is_admin():
            abort(403)
        return fn(*args, **kwargs)
    return wrapped
def rows(query,args=()):
    with db() as con: return con.execute(query,args).fetchall()
def one(query,args=()):
    with db() as con: return con.execute(query,args).fetchone()
def parse_local(value): return datetime.fromisoformat(value)
def fmt(value):
    try: return datetime.fromisoformat(value).strftime('%b %d, %I:%M %p')
    except Exception: return value or '—'

def login_required(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        if not session.get('user_id'): return redirect(url_for('login', next=request.path))
        g.user=one('SELECT id,username FROM users WHERE id=?',(session['user_id'],))
        if not g.user:
            session.clear(); return redirect(url_for('login'))
        return fn(*args,**kwargs)
    return wrapped

@app.context_processor
def helpers():
    return {
        "fmt": fmt,
        "statuses": STATUSES,
        "current_user": getattr(g, "user", None),
        "is_admin": current_user_is_admin(),
    }

@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=request.form.get('password','')
        confirm=request.form.get('confirm_password','')
        if len(username)<3 or len(username)>80:
            flash('Username must be between 3 and 80 characters.','error')
        elif len(password)<10:
            flash('Use a password with at least 10 characters.','error')
        elif password!=confirm:
            flash('Passwords do not match.','error')
        else:
            try:
                uid=str(uuid.uuid4())
                with db() as con:
                    con.execute('INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)',
                                (uid,username,generate_password_hash(password),now_iso()))
                    add_activity(con, uid, username, 'registered', 'account', uid, 'New account registered')
                session.clear(); session['user_id']=uid; session['username']=username; session.permanent=True
                flash('Your private AeroFlow account is ready.','success')
                return redirect(url_for('dashboard'))
            except sqlite3.IntegrityError: flash('That username is already registered. Please choose another.','error')
    return render_template('auth.html',mode='register')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        username=request.form.get('username','').strip()
        user=one('SELECT * FROM users WHERE username=? COLLATE NOCASE',(username,))
        if user and check_password_hash(user['password_hash'],request.form.get('password','')):
            with db() as con:
                add_activity(con, user['id'], user['username'], 'login', 'account', user['id'], 'Successful sign-in')
            session.clear(); session['user_id']=user['id']; session['username']=user['username']; session.permanent=True
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid username or password.','error')
    return render_template('auth.html',mode='login')

@app.route('/logout',methods=['POST'])
def logout():
    if session.get('user_id'):
        user=one('SELECT id,username FROM users WHERE id=?',(session['user_id'],))
        if user:
            with db() as con:
                add_activity(con, user['id'], user['username'], 'logout', 'account', user['id'], 'Signed out')
    session.clear(); flash('You have been logged out.','success'); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    uid=g.user['id']
    flights=rows('SELECT * FROM flights WHERE user_id=? ORDER BY departure_time',(uid,))
    pilots=rows('SELECT * FROM pilots WHERE user_id=? ORDER BY pilot_code',(uid,))
    aircraft=rows('SELECT * FROM aircraft WHERE user_id=? ORDER BY registration',(uid,))
    upcoming=[f for f in flights if parse_local(f['departure_time'])>datetime.now() and f['status']!='Cancelled'][:5]
    stats=[('Total flights',len(flights),'✈'),('In the air',sum(f['status']=='In Air' for f in flights),'➤'),('Delayed / cancelled',sum(f['status'] in ('Delayed','Cancelled') for f in flights),'⚠'),('Pilots on roster',len(pilots),'♙')]
    counts={s:sum(f['status']==s for f in flights) for s in STATUSES}
    ac={a['id']:a['registration'] for a in aircraft}; pl={p['id']:p['name'] for p in pilots}
    return render_template('dashboard.html',stats=stats,counts=counts,upcoming=upcoming,ac=ac,pl=pl)

@app.route('/flights')
@login_required
def flights_page():
    uid=g.user['id']; q=request.args.get('q','').strip().lower(); status=request.args.get('status','All'); pilot_filter=request.args.get('pilot','All')
    sql='''SELECT f.*,p.name AS pilot_name,p.pilot_code,a.registration FROM flights f
           LEFT JOIN pilots p ON p.id=f.pilot_id AND p.user_id=f.user_id
           LEFT JOIN aircraft a ON a.id=f.aircraft_id AND a.user_id=f.user_id WHERE f.user_id=?'''
    args=[uid]
    if status!='All': sql+=' AND f.status=?'; args.append(status)
    if pilot_filter!='All': sql+=' AND f.pilot_id=?'; args.append(pilot_filter)
    if q:
        sql+=' AND (lower(f.flight_number) LIKE ? OR lower(f.origin) LIKE ? OR lower(f.destination) LIKE ?)'; args += [f'%{q}%']*3
    sql+=' ORDER BY f.departure_time'
    flights=[dict(f) for f in rows(sql,args)]
    pilots=[dict(p) for p in rows('SELECT * FROM pilots WHERE user_id=? ORDER BY pilot_code',(uid,))]
    aircraft=[dict(a) for a in rows('SELECT * FROM aircraft WHERE user_id=? ORDER BY registration',(uid,))]
    return render_template('flights.html',flights=flights,pilots=pilots,aircraft=aircraft,q=q,status=status,pilot_filter=pilot_filter)

@app.route('/pilots')
@login_required
def pilots_page():
    uid=g.user['id']; q=request.args.get('q','').strip().lower()
    pilots=rows('''SELECT p.*,(SELECT COUNT(*) FROM flights f WHERE f.user_id=p.user_id AND f.pilot_id=p.id AND f.status!='Cancelled') AS assigned
                  FROM pilots p WHERE p.user_id=? AND (lower(p.name) LIKE ? OR lower(p.pilot_code) LIKE ?) ORDER BY p.pilot_code''',(uid,f'%{q}%',f'%{q}%'))
    return render_template('pilots.html',pilots=[dict(p) for p in pilots],q=q)

@app.route('/aircraft')
@login_required
def aircraft_page():
    aircraft = rows(
        'SELECT * FROM aircraft WHERE user_id=? ORDER BY registration',
        (g.user['id'],)
    )
    return render_template('aircraft.html', aircraft=[dict(a) for a in aircraft])

@app.route('/save/<kind>',methods=['POST'])
@login_required
def save_record(kind):
    if kind not in ('flights','pilots','aircraft'): return 'Invalid record type',404
    data=request.form; uid=g.user['id']; rid=data.get('id') or str(uuid.uuid4()); created=now_iso()
    is_update=bool(data.get('id'))
    try:
        with db() as con:
            if kind=='pilots':
                values=(data['pilot_code'].strip().upper(),data['name'].strip(),data.get('rank','Captain'),data.get('license_number','').strip() or None,int(data.get('flight_hours',0) or 0))
                if is_update:
                    cur=con.execute('UPDATE pilots SET pilot_code=?,name=?,rank=?,license_number=?,flight_hours=? WHERE id=? AND user_id=?',values+(rid,uid))
                else:
                    cur=con.execute('INSERT INTO pilots(id,user_id,pilot_code,name,rank,license_number,flight_hours,created_at) VALUES(?,?,?,?,?,?,?,?)',(rid,uid)+values+(created,))
                if cur.rowcount:
                    add_activity(con, uid, g.user['username'], 'updated' if is_update else 'created',
                                 'pilot', rid, f'Pilot {values[0]} — {values[1]}')
            elif kind=='aircraft':
                values=(data['registration'].strip().upper(),data['model'].strip(),int(data.get('capacity',180) or 180),data.get('status','Active'))
                if is_update:
                    cur=con.execute('UPDATE aircraft SET registration=?,model=?,capacity=?,status=? WHERE id=? AND user_id=?',values+(rid,uid))
                else:
                    cur=con.execute('INSERT INTO aircraft(id,user_id,registration,model,capacity,status,created_at) VALUES(?,?,?,?,?,?,?)',(rid,uid)+values+(created,))
                if cur.rowcount:
                    add_activity(con, uid, g.user['username'], 'updated' if is_update else 'created',
                                 'aircraft', rid, f'Aircraft {values[0]} — {values[1]}')
            else:
                dep=parse_local(data['departure_time']); arr=parse_local(data['arrival_time'])
                if arr<=dep: flash('Arrival must be after departure.','error'); return redirect(url_for('flights_page'))
                pilot_id=data.get('pilot_id') or None; aircraft_id=data.get('aircraft_id') or None
                for table,ref in (('pilots',pilot_id),('aircraft',aircraft_id)):
                    if ref and not con.execute(f'SELECT id FROM {table} WHERE id=? AND user_id=?',(ref,uid)).fetchone():
                        flash('Selected pilot or aircraft is not in your account.','error'); return redirect(url_for('flights_page'))
                if pilot_id:
                    conflict=con.execute('''SELECT flight_number FROM flights WHERE user_id=? AND pilot_id=? AND id!=? AND status!='Cancelled' AND departure_time<? AND arrival_time>? LIMIT 1''',(uid,pilot_id,rid,arr.isoformat(timespec='seconds'),dep.isoformat(timespec='seconds'))).fetchone()
                    if conflict: flash(f"Pilot already assigned to {conflict['flight_number']} at that time.",'error'); return redirect(url_for('flights_page'))
                values=(data['flight_number'].strip().upper(),data['origin'].strip().upper(),data['destination'].strip().upper(),dep.isoformat(timespec='seconds'),arr.isoformat(timespec='seconds'),data.get('status','Scheduled'),aircraft_id,pilot_id)
                if is_update:
                    cur=con.execute('UPDATE flights SET flight_number=?,origin=?,destination=?,departure_time=?,arrival_time=?,status=?,aircraft_id=?,pilot_id=? WHERE id=? AND user_id=?',values+(rid,uid))
                else:
                    cur=con.execute('INSERT INTO flights(id,user_id,flight_number,origin,destination,departure_time,arrival_time,status,aircraft_id,pilot_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,uid)+values+(created,))
                if cur.rowcount:
                    add_activity(con, uid, g.user['username'], 'updated' if is_update else 'created',
                                 'flight', rid, f'Flight {values[0]} — {values[1]} to {values[2]} ({values[5]})')
        flash('Changes saved.' if is_update else 'Record added.','success')
    except sqlite3.IntegrityError: flash('That flight number, pilot code or aircraft registration already exists in your account.','error')
    except (ValueError,KeyError): flash('Please check the information entered and try again.','error')
    return redirect(url_for({'flights':'flights_page','pilots':'pilots_page','aircraft':'aircraft_page'}[kind]))

@app.route('/delete/<kind>/<rid>',methods=['POST'])
@login_required
def delete_record(kind,rid):
    if kind not in ('flights','pilots','aircraft'): return 'Invalid record type',404
    with db() as con:
        record=con.execute(f'SELECT * FROM {kind} WHERE id=? AND user_id=?',(rid,g.user['id'])).fetchone()
        if record:
            if kind=='flights':
                details=f"Flight {record['flight_number']} — {record['origin']} to {record['destination']}"
            elif kind=='pilots':
                details=f"Pilot {record['pilot_code']} — {record['name']}"
            else:
                details=f"Aircraft {record['registration']} — {record['model']}"
            con.execute(f'DELETE FROM {kind} WHERE id=? AND user_id=?',(rid,g.user['id']))
            add_activity(con, g.user['id'], g.user['username'], 'deleted',
                         {'flights':'flight','pilots':'pilot','aircraft':'aircraft'}[kind], rid, details)
    flash('Record deleted.' if record else 'Record was not found in your account.','success' if record else 'error')
    return redirect(url_for({'flights':'flights_page','pilots':'pilots_page','aircraft':'aircraft_page'}[kind]))

@app.route('/admin/activity')
@login_required
@admin_required
def admin_activity():
    activity=rows('''SELECT occurred_at,username,action,entity_type,entity_id,details
                     FROM activity_logs ORDER BY id DESC LIMIT 300''')
    summary=rows('''SELECT u.username,u.created_at,
        (SELECT COUNT(*) FROM activity_logs l WHERE l.user_id=u.id AND l.action='login') AS login_count,
        (SELECT MAX(occurred_at) FROM activity_logs l WHERE l.user_id=u.id AND l.action='login') AS last_login,
        (SELECT COUNT(*) FROM flights f WHERE f.user_id=u.id) AS flights_count,
        (SELECT COUNT(*) FROM pilots p WHERE p.user_id=u.id) AS pilots_count,
        (SELECT COUNT(*) FROM aircraft a WHERE a.user_id=u.id) AS aircraft_count
        FROM users u ORDER BY u.created_at DESC''')
    return render_template('admin_activity.html', activity=activity, summary=summary)

@app.route('/admin/activity.xlsx')
@login_required
@admin_required
def export_activity():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb=Workbook()
    ws=wb.active
    ws.title='Activity Log'
    ws.append(['Date and time','Username','Action','Record type','Record ID','Details'])
    for r in rows('''SELECT occurred_at,username,action,entity_type,entity_id,details
                     FROM activity_logs ORDER BY id DESC'''):
        ws.append([r['occurred_at'],r['username'],r['action'],r['entity_type'],r['entity_id'],r['details']])
    summary=wb.create_sheet('User Summary')
    summary.append(['Username','Account created','Successful logins','Last login','Flights','Pilots','Aircraft'])
    for r in rows('''SELECT u.username,u.created_at,
        (SELECT COUNT(*) FROM activity_logs l WHERE l.user_id=u.id AND l.action='login') AS login_count,
        (SELECT MAX(occurred_at) FROM activity_logs l WHERE l.user_id=u.id AND l.action='login') AS last_login,
        (SELECT COUNT(*) FROM flights f WHERE f.user_id=u.id) AS flights_count,
        (SELECT COUNT(*) FROM pilots p WHERE p.user_id=u.id) AS pilots_count,
        (SELECT COUNT(*) FROM aircraft a WHERE a.user_id=u.id) AS aircraft_count
        FROM users u ORDER BY u.created_at'''):
        summary.append([r['username'],r['created_at'],r['login_count'],r['last_login'],
                        r['flights_count'],r['pilots_count'],r['aircraft_count']])

    for sheet in wb.worksheets:
        sheet.freeze_panes='A2'
        sheet.auto_filter.ref=sheet.dimensions
        for cell in sheet[1]:
            cell.font=Font(bold=True,color='FFFFFF')
            cell.fill=PatternFill('solid',fgColor='17365D')
            cell.alignment=Alignment(horizontal='center')
        for col in sheet.columns:
            width=min(max(max(len(str(c.value or '')) for c in col)+2,12),48)
            sheet.column_dimensions[get_column_letter(col[0].column)].width=width

    output=BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output,as_attachment=True,download_name='AeroFlow_User_Activity_Report.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

with app.app_context(): init_db()

if __name__=='__main__': app.run(debug=False)

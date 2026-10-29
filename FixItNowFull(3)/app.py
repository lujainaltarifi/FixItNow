import os
import sqlite3
import uuid
import requests
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder='static')
app.secret_key = '123'
DB_PATH = 'database.db'
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SPECIALITIES = ["Carpenter", "Electrician", "Plumber", "HVAC Technician", "Painter"]
MAINTENANCE_TYPES = ["Electrical", "Plumbing", "Carpentry", "Painting", "AC"]
AREAS = [
    "Amman", "Zarqa", "Irbid", "Aqaba", "Madaba",
    "Jerash", "Ajloun", "Mafraq", "Karak", "Ma'an", "Tafilah"
]

ISSUES = {
    "water_leak": ("Water Leak","تسريب ماء",(50,100)),
    "faucet":     ("Broken Faucet","حنفية مكسورة",(30,60)),
    "electrical": ("Electrical Short","قصر كهربائي",(70,150)),
    "ac":         ("AC Not Cooling","تكييف لا يبرد",(80,200)),
    "drain":      ("Clogged Drain","انسداد صرف",(40,80))
}

def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def init_db():
    conn = connect_db()
    c = conn.cursor()
    c.execute('''
      CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,
        phone TEXT,
        speciality TEXT,
        maintenance_type TEXT,
        area TEXT
      )
    ''')
    c.execute('''
      CREATE TABLE IF NOT EXISTS logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_msg TEXT,
        bot_msg TEXT,
        attachment TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    ''')
    c.execute('''
      CREATE TABLE IF NOT EXISTS ratings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        rating TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    ''')
    conn.commit()
    conn.close()

init_db()

GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN", "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")
GITHUB_ENDPOINT = "https://models.github.ai/inference"
MODEL_NAME      = "openai/gpt-4.1"
HEADERS         = {"Content-Type":"application/json","Authorization":f"Bearer {GITHUB_TOKEN}"}

def db_execute(query, args=(), fetchone=False, commit=False):
    conn = connect_db()
    c = conn.cursor()
    c.execute(query, args)
    result = c.fetchone() if fetchone else c.fetchall()
    if commit:
        conn.commit()
    conn.close()
    return result

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

@app.before_request
def ensure_lang():
    session.setdefault('lang', 'ar')

@app.route('/lang/<lang>')
def set_lang(lang):
    if lang in ('ar', 'en'):
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        role = request.form['role']
        u = request.form['username'].strip()
        e = request.form['email'].strip()
        p = request.form['password']
        hashed = generate_password_hash(p)
        phone = request.form.get('phone')
        specialty = request.form.get('specialty')
        maint_type = request.form.get('maintenance_type')
        area = request.form.get('area')
        try:
            db_execute(
                'INSERT INTO users(username,email,password,role,phone,speciality,maintenance_type,area) VALUES(?,?,?,?,?,?,?,?)',
                (u, e, hashed, role, phone, specialty, maint_type, area),
                commit=True
            )
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return render_template('signup.html', error=True,
                                   default_role=role,
                                   specialities=SPECIALITIES,
                                   maintenance_types=MAINTENANCE_TYPES,
                                   areas=AREAS)
    return render_template('signup.html',
                           default_role='user',
                           specialities=SPECIALITIES,
                           maintenance_types=MAINTENANCE_TYPES,
                           areas=AREAS)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        e = request.form['email'].strip()
        p = request.form['password']
        user = db_execute(
            'SELECT id,username,password FROM users WHERE email=?',
            (e,), fetchone=True
        )
        if user and check_password_hash(user[2], p):
            session['user_id'], session['username'] = user[0], user[1]
            return redirect(url_for('chat'))
        return render_template('login.html', error=True)
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html', username=session.get('username'))

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    text = (request.form.get('message') or (request.json and request.json.get('message',''))).strip()
    file = request.files.get('attachment')
    attachment_url = None
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1]
        fname = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(UPLOAD_FOLDER, fname)
        file.save(path)
        attachment_url = url_for('static', filename=f"uploads/{fname}")
    if not text and not attachment_url:
        return jsonify(error="Send text or upload a file"), 400
    sys_prompt = "أنت خبير صيانة منازل. عند تواصلك مع العميل، قم بتشخيص العطل خطوة بخطوة واقتراح الحلول."
    user_content = text + (f"\n[Attachment: {attachment_url}]" if attachment_url else "")
    payload = {"model":MODEL_NAME,"messages":[{"role":"system","content":sys_prompt},{"role":"user","content":user_content}]}
    resp = requests.post(f"{GITHUB_ENDPOINT}/chat/completions", headers=HEADERS, json=payload)
    if resp.status_code != 200:
        return jsonify(error="AI service error"), 500
    bot_msg = resp.json()["choices"][0]["message"]["content"]
    db_execute('INSERT INTO logs(user_id,user_msg,bot_msg,attachment) VALUES(?,?,?,?)',
               (session['user_id'], text, bot_msg, attachment_url), commit=True)
    return jsonify(reply=bot_msg, attachment=attachment_url)

@app.route('/estimate', methods=['GET','POST'])
@login_required
def estimate():
    price = None
    if request.method == 'POST':
        key = request.form.get('issue')
        low, high = ISSUES[key][2]
        price = f"{low}–{high}"
    return render_template('estimate.html', issues=ISSUES, price=price)

@app.route('/rate', methods=['GET','POST'])
@login_required
def rate():
    thanked = False
    if request.method == 'POST':
        r = request.form.get('rating')
        db_execute('INSERT INTO ratings(user_id,rating) VALUES(?,?)',
                   (session['user_id'], r), commit=True)
        thanked = True
    return render_template('rate.html', thanked=thanked)

@app.route('/confirm', methods=['GET','POST'])
@login_required
def confirm():
    tech = request.values.get('tech')
    if request.method == 'POST':
        date = request.form['date']
        time = request.form['time']
        return render_template('confirmed.html', tech=tech, date=date, time=time)
    return render_template('confirm.html', tech=tech)

@app.route('/find')
@login_required
def find():
    technicians = [
        {"name":"أحمد العمري","rating":4.6,"distance_ar":"١.٢ كم","distance_en":"1.2 km",
         "phone":"0791234567","phone_display":"٠٧٩-١٢٣-٤٥٦٧","lat":31.95,"lng":35.88},
        {"name":"سارة الخطيب","rating":4.8,"distance_ar":"٢.٣ كم","distance_en":"2.3 km",
         "phone":"0792345678","phone_display":"٠٧٩-٢٣٤-٥٦٧٨","lat":31.97,"lng":35.92},
        {"name":"خالد منصور","rating":4.4,"distance_ar":"٣.١ كم","distance_en":"3.1 km",
         "phone":"0793456789","phone_display":"٠٧٩-٣٤٥-٦٧٨٩","lat":31.96,"lng":35.89},
        {"name":"ميساء الدويكات","rating":4.9,"distance_ar":"٠.٩ كم","distance_en":"0.9 km",
         "phone":"0794567890","phone_display":"٠٧٩-٤٥٦-٧٨٩٠","lat":31.94,"lng":35.93},
        {"name":"عمر سالم","rating":4.5,"distance_ar":"٤.٠ كم","distance_en":"4.0 km",
         "phone":"0795678901","phone_display":"٠٧٩-٥٦٧-٨٩٠١","lat":31.98,"lng":35.90},
        {"name":"فاتن بشناق","rating":4.7,"distance_ar":"٢.٨ كم","distance_en":"2.8 km",
         "phone":"0796789012","phone_display":"٠٧٩-٦٧٨-٩٠١٢","lat":31.92,"lng":35.95},
        {"name":"يزن الرفاعي","rating":4.3,"distance_ar":"٥.٢ كم","distance_en":"5.2 km",
         "phone":"0797890123","phone_display":"٠٧٩-٧٨٩-٠١٢٣","lat":31.93,"lng":35.88},
        {"name":"رنا حمدان","rating":4.6,"distance_ar":"٣.٥ كم","distance_en":"3.5 km",
         "phone":"0798901234","phone_display":"٠٧٩-٨٩٠-١٢٣٤","lat":31.99,"lng":35.87},
        {"name":"أيمن الشهاب","rating":4.2,"distance_ar":"١.٧ كم","distance_en":"1.7 km",
         "phone":"0799012345","phone_display":"٠٧٩-٩٠١-٢٣٤٥","lat":31.90,"lng":35.92},
        {"name":"لمى خليل","rating":4.8,"distance_ar":"٢.١ كم","distance_en":"2.1 km",
         "phone":"0790123456","phone_display":"٠٧٩-٠١٢-٣٤٥٦","lat":31.91,"lng":35.94},
        {"name":"زيد العرموطي","rating":4.4,"distance_ar":"١.٥ كم","distance_en":"1.5 km",
         "phone":"0791122334","phone_display":"٠٧٩-١١٢-٢٢٣٤","lat":31.89,"lng":35.90},
        {"name":"رانيا العبداللات","rating":4.7,"distance_ar":"٣.٢ كم","distance_en":"3.2 km",
         "phone":"0792233445","phone_display":"٠٧٩-٢٢٣-٣٣٤٥","lat":31.88,"lng":35.93},
        {"name":"محمود حسن","rating":4.5,"distance_ar":"٢.٧ كم","distance_en":"2.7 km",
         "phone":"0793344556","phone_display":"٠٧٩-٣٣٤-٤٥٥٦","lat":31.87,"lng":35.89},
        {"name":"هالة العساف","rating":4.9,"distance_ar":"٠.٨ كم","distance_en":"0.8 km",
         "phone":"0794455667","phone_display":"٠٧٩-٤٤٥-٥٦٦٧","lat":31.96,"lng":35.94},
        {"name":"علي القرالة","rating":4.3,"distance_ar":"٤.٣ كم","distance_en":"4.3 km",
         "phone":"0795566778","phone_display":"٠٧٩-٥٥٦-٦٧٧٨","lat":31.94,"lng":35.87},
        {"name":"نور الصغير","rating":4.6,"distance_ar":"١٫٩ كم","distance_en":"1.9 km",
         "phone":"0796677889","phone_display":"٠٧٩-٦٦٧-٧٨٨٩","lat":31.98,"lng":35.95},
        {"name":"طارق عودة","rating":4.2,"distance_ar":"٣.٠ كم","distance_en":"3.0 km",
         "phone":"0797788990","phone_display":"٠٧٩-٧٧٨-٨٩٩٠","lat":31.93,"lng":35.91},
        {"name":"دانا فرحان","rating":4.8,"distance_ar":"٢.٤ كم","distance_en":"2.4 km",
         "phone":"0798899001","phone_display":"٠٧٩-٨٨٩-٩٠٠١","lat":31.92,"lng":35.89},
        {"name":"لين جميل","rating":4.5,"distance_ar":"٥.٠ كم","distance_en":"5.0 km",
         "phone":"0799900112","phone_display":"٠٧٩-٩٩٠-٠١١٢","lat":31.97,"lng":35.88},
        {"name":"سامر البيطار","rating":4.4,"distance_ar":"١.٣ كم","distance_en":"1.3 km",
         "phone":"0791011122","phone_display":"٠٧٩-١٠١-١١٢٢","lat":31.90,"lng":35.90}
    ]
    return render_template('find.html', technicians=technicians)

if __name__ == '__main__':
    app.run(debug=True)

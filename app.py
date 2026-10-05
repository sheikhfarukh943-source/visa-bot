import asyncio
import os
import random
import secrets
from datetime import datetime
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

app = Flask(__name__)

# সেশন সিকিউরিটির জন্য সিক্রেট কি এবং ডেটাবেজ কনফিগারেশন
app.secret_key = secrets.token_hex(16)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# সেশন এবং অ্যাডমিন ট্র্যাকিং ডাটা
active_sessions = {}
admin_stats = {
    "total_uploads": 0,
    "successful_bookings": 0,
    "failed_bookings": 0,
    "history": []
}

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
PROXY_SERVER = os.getenv("PROXY_URL", "")

# --- ডেটাবেজ মডেল (User Table) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="User") # 'Admin' অথবা 'User'

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

# ডিফল্ট অ্যাডমিন অ্যাকাউন্ট তৈরি করা
with app.app_context():
    db.create_all()
    if not User.query.filter_by(role="Admin").first():
        admin = User(username="admin", role="Admin")
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()

# --- রাউটস ও লজিক (Routes) ---

@app.route("/")
def home():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    if session.get('role') == 'Admin':
        return redirect(url_for('admin_dashboard'))
    return render_template("index.html", username=session.get('username'))

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            return redirect(url_for('home'))
        else:
            return render_template("login.html", error="ইউজারনেম বা পাসওয়ার্ড ভুল।")
    return render_template("login.html")

@app.route("/admin")
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('login_page'))
    all_users = User.query.all()
    return render_template("admin.html", users=all_users, admin_name=session.get('username'))

@app.route("/admin/create-user", methods=["POST"])
def create_user():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return jsonify({"status": "error", "message": "অনুমতি নেই"}), 403
        
    data = request.json
    username = data.get("username")
    password = data.get("password")
    role = data.get("role", "User")

    if User.query.filter_by(username=username).first():
        return jsonify({"status": "error", "message": "ইউজারনেম ইতিমধ্যে বিদ্যমান।"}), 400

    new_user = User(username=username, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"status": "success", "message": f"'{username}' অ্যাকাউন্টটি তৈরি হয়েছে। "})

@app.route("/admin/stats", methods=["GET"])
def get_admin_stats():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return jsonify({"status": "error", "message": "অনুমতি নেই"}), 403
    return jsonify(admin_stats)

@app.route("/pre-load", methods=["POST"])
def pre_load_data():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "লগইন করা আবশ্যক"}), 401

    center = request.form.get("center")
    passport = request.form.get("passport")
    phone = request.form.get("phone")
    web_file = request.files.get("web_file")

    if not all([center, passport, phone, web_file]):
        return jsonify({"status": "error", "message": "সব তথ্য ও ফাইল দিন"}), 400

    filename = web_file.filename
    file_path = os.path.join(UPLOAD_FOLDER, f"{passport}_{filename}")
    web_file.save(file_path)
    admin_stats["total_uploads"] += 1

    asyncio.create_task(run_visa_scheduler(passport, center, passport, phone, file_path, filename))
    return jsonify({"status": "queued", "session_id": passport, "message": "ফাইল আপলোড ট্র্যাক করা হয়েছে।"})

async def run_visa_scheduler(session_id, center, passport, phone, file_path, filename):
    async with async_playwright() as p:
        browser_args = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
        proxy_dict = {"server": PROXY_SERVER} if PROXY_SERVER else None
        browser = await p.chromium.launch(headless=True, args=browser_args, proxy=proxy_dict)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = await context.new_page()
        await stealth_async(page)

        active_sessions[session_id] = {"status": "server_waiting", "otp_submitted": asyncio.Event(), "otp_code": None, "result": None}
        log_entry = {"passport": passport, "phone": phone, "filename": filename, "center": center, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": "Pending"}
        admin_stats["history"].append(log_entry)

        try:
            while True:
                try:
                    await page.goto("https://ivacbd.com", timeout=20000, wait_until="commit")
                    if await page.query_selector("input[name='passport_number']"): break
                except Exception: pass
                await asyncio.sleep(random.uniform(3.0, 6.0))

            active_sessions[session_id]["status"] = "processing_fields"
            await page.fill("input[name='passport_number']", passport)
            await page.fill("input[name='mobile_number']", phone)
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await page.click("#next-step-btn")

            await page.wait_for_selector("input[name='otp_code_input']", timeout=30000)
            active_sessions[session_id]["status"] = "waiting_for_otp"
            await active_sessions[session_id]["otp_submitted"].wait()

            user_otp = active_sessions[session_id]["otp_code"]
            await page.fill("input[name='otp_code_input']", user_otp)
            await page.click("#verify-otp-btn")

            await page.wait_for_selector("input[type='file']", timeout=15000)
            await page.set_input_files("input[type='file']", file_path)
            await page.select_option("select[name='visa_center']", label=center)
            await page.click("#confirm-details-btn")

            await page.wait_for_selector("#confirm-booking-btn", timeout=15000)
            await page.click("#confirm-booking-btn")

            await page.wait_for_url("**/payment**", timeout=40000)
            admin_stats["successful_bookings"] += 1
            log_entry["status"] = "Success"
            active_sessions[session_id]["result"] = {"status": "success", "message": "স্লট কনফার্ম!", "payment_url": page.url}
            await asyncio.sleep(600)
        except Exception as e:
            admin_stats["failed_bookings"] += 1
            log_entry["status"] = f"Failed ({str(e)})"
            active_sessions[session_id]["result"] = {"status": "error", "message": str(e)}
        finally:
            active_sessions[session_id]["status"] = "completed"
            await browser.close()
            if os.path.exists(file_path): os.remove(file_path)

@app.route("/poll-status/<session_id>", methods=["GET"])
def poll_status(session_id):
    if 'user_id' not in session: return jsonify({"status": "unauthorized"}), 401
    session_data = active_sessions.get(session_id)
    if not session_data: return jsonify({"status": "not_found"})
    return jsonify({"status": session_data["status"], "result": session_data.get("result")})

@app.route("/submit-otp", methods=["POST"])
def submit_otp():
    if 'user_id' not in session: return jsonify({"status": "unauthorized"}), 401
    data = request.json
    session_data = active_sessions.get(data.get("session_id"))
    if session_data and session_data["status"] == "waiting_for_otp":
        session_data["otp_code"] = data.get("otp")
        session_data["otp_submitted"].set()
        return jsonify({"status": "otp_injected"})
    return jsonify({"status": "error", "message": "সেশন সক্রিয় নেই।"}), 400

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login_page'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

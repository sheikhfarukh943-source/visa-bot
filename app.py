import asyncio
import os
import random
import secrets
from datetime import datetime
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

UPLOAD_FOLDER = 'uploaded_files'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# রিয়েল-টাইম সেশন ট্র্যাকিং ডাটা ডিকশনারি
active_sessions = {}
admin_stats = {"total_uploads": 0, "successful_bookings": 0, "failed_bookings": 0, "history": []}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="User")

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin_farukh").first():
        admin = User(username="admin_farukh", role="Admin")
        admin.set_password("Farukh@1997Lima")
        db.session.add(admin)
        db.session.commit()

@app.route("/")
def home():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    if session.get('role') == 'Admin': return redirect(url_for('admin_dashboard'))
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username")).first()
        if user and user.check_password(request.form.get("password")):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            return redirect(url_for('home'))
        return render_template("login.html", error="ইউজারনেম বা পাসওয়ার্ড ভুল।")
    return render_template("login.html")

@app.route("/admin")
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'Admin': return redirect(url_for('login_page'))
    all_users = User.query.all()
    return render_template("admin.html", users=all_users, stats=admin_stats, admin_name=session.get('username'))

@app.route("/pre-load-group", methods=["POST"])
def pre_load_group():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    
    center = request.form.get("center")
    visa_type = request.form.get("visa_type")
    ivac_phone = request.form.get("ivac_phone")
    ivac_pass = request.form.get("ivac_pass")
    
    if not ivac_phone or not ivac_pass:
        flash("❌ IVAC লগইন নম্বর এবং পাসওয়ার্ড প্রদান করুন。", "error")
        return redirect(url_for('admin_dashboard'))

    file_paths = []
    for i in range(1, 5):
        file_obj = request.files.get(f"file_{i}")
        if i == 1 and (not file_obj or file_obj.filename == ''):
            flash("❌ মেম্বার ১ (Primary Webfile) বাধ্যতামূলক।", "error")
            return redirect(url_for('admin_dashboard'))
            
        if file_obj and file_obj.filename != '':
            filename = f"{ivac_phone}_member_{i}_{file_obj.filename}"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file_obj.save(file_path)
            file_paths.append(file_path)

    admin_stats["total_uploads"] += 1
    session_id = f"session_{ivac_phone}_{int(datetime.now().timestamp())}"
    
    # ব্যাকএন্ড মেমরিতে সেশনটি চালু করা হলো
    active_sessions[session_id] = {
        "status": "server_waiting", 
        "otp_submitted": asyncio.Event(), 
        "otp_code": None, 
        "result": None,
        "phone": ivac_phone,
        "center": center,
        "visa_type": visa_type
    }
    
    # সিমুলেটেড অ্যাসিনক্রোনাস আইভ্যাক প্রসেসর ট্র্যাকার টাস্ক
    asyncio.create_task(mock_ivac_browser_worker(session_id, center, visa_type, ivac_phone, ivac_pass, file_paths))
    
    flash(f"🟢 সেশন '{session_id}' তৈরি হয়েছে। উপরে লাইভ মনিটরে ওটিপি ও স্ট্যাটাস ট্র্যাক করুন।", "success")
    return redirect(url_for('admin_dashboard'))

async def mock_ivac_browser_worker(session_id, center, visa_type, ivac_phone, ivac_pass, file_paths):
    try:
        await asyncio.sleep(4) 
        active_sessions[session_id]["status"] = "processing_fields"
        
        await asyncio.sleep(5)
        # ওটিপি স্টেজ ট্রিগার—এখানে বট এসে কোড ইনপুটের অপেক্ষা করবে
        active_sessions[session_id]["status"] = "waiting_for_otp"
        await active_sessions[session_id]["otp_submitted"].wait()
        
        # ওটিপি সাবমিট হওয়ার পর স্লট বুকিং প্রসেস শুরু হবে
        active_sessions[session_id]["status"] = "slot_booking_in_progress"
        await asyncio.sleep(6)
        
        active_sessions[session_id]["status"] = "completed"
        active_sessions[session_id]["result"] = {"status": "success", "payment_url": "https://ivacbd.com"}
        admin_stats["successful_bookings"] += 1
        
        admin_stats["history"].append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "passport": ivac_phone,
            "center": center,
            "filename": f"{visa_type} (সফল বুকিং)",
            "status": "Success"
        })
    except Exception as e:
        active_sessions[session_id]["status"] = "completed"
        active_sessions[session_id]["result"] = {"status": "error", "message": str(e)}
        admin_stats["failed_bookings"] += 1

@app.route("/admin/create-user", methods=["POST"])
def create_user():
    if 'user_id' not in session or session.get('role') != 'Admin': return redirect(url_for('login_page'))
    username = request.form.get("username")
    password = request.form.get("password")
    role = request.form.get("role")
    
    if User.query.filter_by(username=username).first():
        flash("❌ ইউজারনেম ইতিমধ্যে বিদ্যমান।", "error")
        return redirect(url_for('admin_dashboard'))
        
    new_user = User(username=username, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    flash(f"🟢 নতুন ব্যবহারকারী '{username}' সফলভাবে তৈরি হয়েছে।", "success")
    return redirect(url_for('admin_dashboard'))

@app.route("/api/live-sessions", methods=["GET"])
def get_live_sessions():
    # লাইভ সক্রিয় সেশনগুলো ফ্রন্টএন্ডে পাঠানোর এপিআই
    sessions_list = []
    for k, v in active_sessions.items():
        sessions_list.append({
            "id": k, "phone": v["phone"], "center": v["center"],
            "visa_type": v["visa_type"], "status": v["status"]
        })
    return jsonify(sessions_list)

@app.route("/api/submit-otp", methods=["POST"])
def api_submit_otp():
    data = request.json
    s_id = data.get("session_id")
    otp = data.get("otp")
    if s_id in active_sessions and active_sessions[s_id]["status"] == "waiting_for_otp":
        active_sessions[s_id]["otp_code"] = otp
        active_sessions[s_id]["otp_submitted"].set()
        return jsonify({"status": "success", "message": "ওটিপি ব্যাকএন্ড বটের কাছে পাঠানো হয়েছে। "})
    return jsonify({"status": "error", "message": "সেশন সক্রিয় নেই বা ওটিপির জন্য অপেক্ষা করছে না।"})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login_page'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

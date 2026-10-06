import os
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

# সেশন এবং আপলোড লগ ডাটা ব্যাকএন্ডে স্থায়ী ও স্ট্যাটিক রাখা হলো
admin_stats = {
    "total_uploads": 0, 
    "successful_bookings": 0, 
    "failed_bookings": 0, 
    "history": [], 
    "last_message": None,
    "live_sessions": [] # ফ্রন্টএন্ড পোলিংয়ের জন্য মেমরিতে ফিক্সড লিস্ট
}

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
    return render_template("admin.html", users=User.query.all(), stats=admin_stats, admin_name=session.get('username'))

@app.route("/pre-load-group", methods=["POST"])
def pre_load_group():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    
    center = request.form.get("center")
    visa_type = request.form.get("visa_type")
    ivac_phone = request.form.get("ivac_phone")
    ivac_pass = request.form.get("ivac_pass")
    
    if not ivac_phone or not ivac_pass:
        admin_stats["last_message"] = "❌ IVAC লগইন নম্বর এবং পাসওয়ার্ড প্রদান করুন।"
        return redirect(url_for('admin_dashboard'))

    uploaded_count = 0
    for i in range(1, 5):
        file_obj = request.files.get(f"file_{i}")
        if i == 1 and not file_obj:
            admin_stats["last_message"] = "❌ মেম্বার ১ (Primary Webfile) বাধ্যতামূলক।"
            return redirect(url_for('admin_dashboard'))
            
        if file_obj and file_obj.filename != '':
            filename = f"{ivac_phone}_member_{i}_{file_obj.filename}"
            file_obj.save(os.path.join(UPLOAD_FOLDER, filename))
            uploaded_count += 1

    admin_stats["total_uploads"] += 1
    session_id = f"session_{ivac_phone}_{int(datetime.now().timestamp())}"
    
    # ফাইল আপলোড হওয়ার সাথে সাথে ওটিপি উইজেট লাইভ অন করার জন্য স্ট্যাটিক সেশন এন্ট্রি
    admin_stats["live_sessions"] = [{
        "id": session_id,
        "phone": ivac_phone,
        "center": center,
        "visa_type": visa_type,
        "status": "waiting_for_otp" # ওটিপি বক্স সবসময় ফিক্সড স্ক্রিনে দেখাবে
    }]

    admin_stats["history"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "passport": ivac_phone,
        "center": center,
        "filename": f"{visa_type} ({uploaded_count} Files)",
        "status": "Processed"
    })
    
    admin_stats["last_message"] = "🟢 তথ্য ও ওয়েব ফাইল ড্যাশবোর্ডে সফলভাবে লোড হয়েছে।"
    return redirect(url_for('admin_dashboard'))

@app.route("/api/live-sessions", methods=["GET"])
def get_live_sessions():
    return jsonify(admin_stats["live_sessions"])

@app.route("/api/submit-otp", methods=["POST"])
def api_submit_otp():
    data = request.json
    s_id = data.get("session_id")
    otp = data.get("otp")
    
    if admin_stats["live_sessions"] and admin_stats["live_sessions"][0]["id"] == s_id:
        admin_stats["live_sessions"][0]["status"] = "slot_booking_in_progress"
        return jsonify({"status": "success", "message": f"ওটিপি কোড [{otp}] সফলভাবে সাবমিট হয়েছে! স্লট বুকিং চেক করা হচ্ছে..."})
    return jsonify({"status": "error", "message": "কোনো সক্রিয় সেশন খুঁজে পাওয়া যায়নি। "})

@app.route("/admin/create-user", methods=["POST"])
def create_user():
    if 'user_id' not in session or session.get('role') != 'Admin': return redirect(url_for('login_page'))
    
    username = request.form.get("username")
    password = request.form.get("password")
    role = request.form.get("role")
    
    if User.query.filter_by(username=username).first(): 
        admin_stats["last_message"] = "❌ ইউজারনেম ইতিমধ্যে বিদ্যমান।"
        return redirect(url_for('admin_dashboard'))
        
    new_user = User(username=username, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    
    admin_stats["last_message"] = f"🟢 নতুন ব্যবহারকারী '{username}' তৈরি হয়েছে।"
    return redirect(url_for('admin_dashboard'))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login_page'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

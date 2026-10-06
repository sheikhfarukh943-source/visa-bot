import os
import secrets
from datetime import datetime
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# SQLite ডাটাবেজ কনফিগারেশন
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

UPLOAD_FOLDER = 'uploaded_files'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# লগইন ট্র্যাকিং ডেটা
admin_stats = {
    "total_uploads": 0,
    "successful_bookings": 0,
    "failed_bookings": 0,
    "history": []
}

# --- ব্যবহারকারী টেবিল মডেল ---
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

# ডিফল্ট অ্যাডমিন অ্যাকাউন্ট তৈরি
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin_farukh").first():
        admin = User(username="admin_farukh", role="Admin")
        admin.set_password("Farukh@1997Lima")
        db.session.add(admin)
        db.session.commit()

# --- রাউটস (Routes) ---

@app.route("/")
def home():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    if session.get('role') == 'Admin':
        return redirect(url_for('admin_dashboard'))
    return render_template("login.html")

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
        return render_template("login.html", error="ইউজারনেম বা পাসওয়ার্ড ভুল।")
    return render_template("login.html")

@app.route("/admin")
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('login_page'))
    return render_template("admin.html", users=User.query.all(), admin_name=session.get('username'))

@app.route("/pre-load-group", methods=["POST"])
def pre_load_group():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "লগইন করা আবশ্যক"}), 401
    
    center = request.form.get("center")
    visa_type = request.form.get("visa_type")
    ivac_user = request.form.get("ivac_user")
    ivac_pass = request.form.get("ivac_pass")
    
    if not ivac_user or not ivac_pass:
        return jsonify({"status": "error", "message": "ইউজার আইডি এবং পাসওয়ার্ড প্রদান করুন।"}), 400

    uploaded_count = 0
    # ৪টি ফাইল আপলোড হ্যান্ডলিং লজিক
    for i in range(1, 5):
        file_obj = request.files.get(f"file_{i}")
        if i == 1 and not file_obj:
            return jsonify({"status": "error", "message": "মেম্বার ১ (Primary Webfile) আপলোড করা বাধ্যতামূলক।"}), 400
            
        if file_obj:
            user_prefix = ivac_user.split('@')[0]
            filename = f"{user_prefix}_member_{i}_{file_obj.filename}"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file_obj.save(file_path)
            uploaded_count += 1

    # ইতিহাস লগে তথ্য যোগ করা
    admin_stats["total_uploads"] += 1
    log_entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "passport": ivac_user,
        "center": center,
        "filename": f"{visa_type} ({uploaded_count} Files)",
        "status": "Processed"
    }
    admin_stats["history"].append(log_entry)
    
    return jsonify({
        "status": "queued", 
        "session_id": user_prefix, 
        "message": "তথ্য ও ফাইলগুলো ডাটাবেজ সিস্টেমে সফলভাবে প্রিলোড হয়েছে।"
    })

@app.route("/admin/create-user", methods=["POST"])
def create_user():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return jsonify({"status": "error", "message": "অনুমতি নেই"}), 403
    
    data = request.json
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")
    
    if User.query.filter_by(username=username).first():
        return jsonify({"status": "error", "message": "ইউজারনেম ইতিমধ্যে বিদ্যমান।"}), 400
        
    new_user = User(username=username, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"status": "success", "message": "নতুন ব্যবহারকারী তৈরি হয়েছে। "})

@app.route("/admin/stats", methods=["GET"])
def get_admin_stats():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return jsonify({"status": "error", "message": "অনুমতি নেই"}), 403
    return jsonify(admin_stats)

@app.route("/poll-status/<session_id>", methods=["GET"])
def poll_status(session_id):
    # ধারণামূলক সেশন রিটার্ন লজিক
    return jsonify({"status": "completed", "result": {"status": "success", "message": "সেশন সম্পন্ন।"}})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login_page'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

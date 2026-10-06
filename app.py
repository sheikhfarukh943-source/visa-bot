import os
import secrets
from datetime import datetime
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

UPLOAD_FOLDER = 'uploaded_files'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# সেশন এবং আপলোড লগ ডাটা মেমরিতে স্থায়ী ও ওপেন রাখা হলো
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
    db.drop_all() # জ্যাম লাগা পুরনো ডেটাবেজ টেবিল সম্পূর্ণ ফ্লাশ ও রিসেট করা হলো
    db.create_all()
    if not User.query.filter_by(username="admin_farukh").first():
        admin = User(username="admin_farukh", role="Admin")
        admin.set_password("Farukh@1997Lima")
        db.session.add(admin)
        db.session.commit()

# শতভাগ ডাইরেক্ট রাউট: পেজে ঢোকা মাত্রই কোনো কন্ডিশন ছাড়া সরাসরি মেইন ড্যাশবোর্ড লোড হবে
@app.route("/")
def home():
    all_users = User.query.all()
    users_list = [{"username": u.username, "role": u.role} for u in all_users]
    live_list = list(active_sessions.values())
    return render_template("admin.html", users_list=users_list, stats=admin_stats, live_sessions=live_list)

@app.route("/admin")
def admin_dashboard():
    return redirect(url_for('home'))

@app.route("/pre-load-group", methods=["POST"])
def pre_load_group():
    center = request.form.get("center")
    visa_type = request.form.get("visa_type")
    ivac_phone = request.form.get("ivac_phone")
    ivac_pass = request.form.get("ivac_pass")
    
    if not ivac_phone or not ivac_pass:
        return redirect(url_for('home'))

    file_obj = request.files.get("file_1")
    if not file_obj or file_obj.filename == '':
        return redirect(url_for('home'))

    uploaded_count = 0
    # ৪ জন মেম্বারের ৪টি ফাইল প্রসেসিং সিস্টেম
    for i in range(1, 5):
        f_obj = request.files.get(f"file_{i}")
        if f_obj and f_obj.filename != '':
            filename = f"{ivac_phone}_member_{i}_{f_obj.filename}"
            f_obj.save(os.path.join(UPLOAD_FOLDER, filename))
            uploaded_count += 1

    admin_stats["total_uploads"] += 1
    session_id = f"session_{ivac_phone}"
    
    active_sessions[session_id] = {
        "id": session_id,
        "phone": ivac_phone,
        "center": center,
        "visa_type": visa_type,
        "status": "waiting_for_otp"
    }

    admin_stats["history"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "passport": ivac_phone,
        "center": center,
        "filename": f"{visa_type} ({uploaded_count} Files)",
        "status": "Processed"
    })
    
    return redirect(url_for('home'))

@app.route("/admin/create-user", methods=["POST"])
def create_user():
    username = request.form.get("username")
    password = request.form.get("password")
    role = request.form.get("role")
    
    if not username or not password:
        return redirect(url_for('home'))
        
    if User.query.filter_by(username=username).first(): 
        return redirect(url_for('home'))
        
    new_user = User(username=username, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    
    return redirect(url_for('home'))

@app.route("/api/live-sessions", methods=["GET"])
def get_live_sessions():
    return jsonify(list(active_sessions.values()))

@app.route("/api/submit-otp", methods=["POST"])
def api_submit_otp():
    data = request.json
    s_id = data.get("session_id")
    if s_id in active_sessions:
        active_sessions[s_id]["status"] = "slot_booking_in_progress"
        return jsonify({"status": "success", "message": "ওটিপি বটের কাছে পাঠানো হয়েছে। "})
    return jsonify({"status": "error", "message": "সেশন সক্রিয় নেই। "})

@app.route("/logout")
def logout():
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

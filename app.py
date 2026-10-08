import os
from flask import Flask, render_template, request, redirect, url_for, flash
from supabase import create_client, Client
from werkzeug.utils import secure_filename
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = "visa-bot-secure-session-key"

# Supabase Connection
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

UPLOAD_FOLDER = '/tmp'
ALLOWED_EXTENSIONS = {'zip', 'html'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    # ডাটাবেজ থেকে এভেইলেবল স্লট নিয়ে আসা
    slots_data = supabase.table("slots").select("*").eq("status", "available").execute()
    return render_template('index.html', slots=slots_data.data)

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/create-group', methods=['POST'])
def create_group():
    group_name = request.form.get('group_name')
    m1 = request.form.get('member_1')
    m2 = request.form.get('member_2')
    m3 = request.form.get('member_3')
    m4 = request.form.get('member_4')
    slot_id = request.form.get('slot_id')
    
    # স্লট বুকিং টাইম লক লজিক (স্লট রিলিজ হওয়ার ২০ মিনিট আগে আপলোড বন্ধ)
    if slot_id:
        slot_res = supabase.table("slots").select("slot_time").eq("id", slot_id).single().execute()
        if slot_res.data:
            slot_time = datetime.fromisoformat(slot_res.data['slot_time'].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            time_diff = (slot_time - now).total_seconds() / 60
            if time_diff <= 20 and time_diff > 0:
                flash("স্লট ওপেন হতে ২০ মিনিটের কম সময় বাকি! ফাইল আপলোড লক হয়ে গেছে।", "danger")
                return redirect(url_for('index'))

    file = request.files.get('web_file')
    file_url = "No File Uploaded"
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        file_url = f"Temporary_Storage/{filename}"

    # Supabase এ ডেটা রাখা
    group_data = {
        "group_name": group_name,
        "member_1_name": m1,
        "member_2_name": m2,
        "member_3_name": m3,
        "member_4_name": m4,
        "uploaded_file_url": file_url
    }
    
    try:
        group_res = supabase.table("group_bookings").insert(group_data).execute()
        if group_res.data and slot_id:
            new_group_id = group_res.data[0]['id']
            # স্বয়ংক্রিয়ভাবে স্লট স্টেটাস pending করা পেমেন্টের জন্য
            supabase.table("slots").update({"status": "pending", "booked_by_group_id": new_group_id}).eq("id", slot_id).execute()
        flash("গ্রুপ এবং ফাইল সফলভাবে যুক্ত হয়েছে! অনুগ্রহ করে পেমেন্ট সম্পন্ন করুন।", "success")
    except Exception as e:
        flash(f"সমস্যা হয়েছে: {str(e)}", "danger")
        
    return redirect(url_for('index'))

@app.route('/submit-payment', methods=['POST'])
def submit_payment():
    slot_id = request.form.get('slot_id')
    txn_id = request.form.get('txn_id')
    try:
        supabase.table("slots").update({"txn_id": txn_id}).eq("id", slot_id).execute()
        flash("আপনার ট্রানজেকশন আইডি জমা দেওয়া হয়েছে। অ্যাডমিন ভেরিফিকেশনের জন্য অপেক্ষা করুন।", "success")
    except Exception as e:
        flash(f"পেমেন্ট আপডেট ব্যর্থ: {str(e)}", "danger")
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
def admin_dashboard():
    bookings = supabase.table("group_bookings").select("*").execute()
    slots_data = supabase.table("slots").select("*").execute()
    return render_template('admin.html', bookings=bookings.data, slots=slots_data.data)

@app.route('/admin/approve-payment/<int:slot_id>', methods=['POST'])
def approve_payment(slot_id):
    try:
        supabase.table("slots").update({"status": "confirmed"}).eq("id", slot_id).execute()
        flash("বুকিং পেমেন্ট সফলভাবে অনুমোদিত হয়েছে!", "success")
    except Exception as e:
        flash(f"অ্যাপ্রুভ করতে সমস্যা হয়েছে: {str(e)}", "danger")
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)

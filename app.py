import os
import sys
from flask import Flask, render_template, request, redirect, url_for, flash
from supabase import create_client, Client
from werkzeug.utils import secure_filename
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = "visa-bot-secure-session-key"

# Supabase Credentials সরাসরি পরিবেশ চলক থেকে রিড করা হচ্ছে
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ডাটাবেজ কানেকশন চেক ও ট্রাই-ক্যাচ ব্লক
try:
    if SUPABASE_URL and SUPABASE_KEY:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    else:
        supabase = None
        print("Warning: Supabase credentials are empty or missing.")
except Exception as e:
    supabase = None
    print(f"Supabase connection error: {e}")

UPLOAD_FOLDER = '/tmp'
ALLOWED_EXTENSIONS = {'zip', 'html'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1).lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    slots_data = []
    if supabase:
        try:
            res = supabase.table("slots").select("*").eq("status", "available").execute()
            slots_data = res.data if res.data else []
        except Exception as e:
            print(f"Database query error: {e}")
    return render_template('index.html', slots=slots_data)

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/create-group', methods=['POST'])
def create_group():
    if not supabase:
        flash("ডাটাবেজ কানেকশন পাওয়া যায়নি!", "danger")
        return redirect(url_for('index'))

    group_name = request.form.get('group_name')
    m1 = request.form.get('member_1')
    m2 = request.form.get('member_2')
    m3 = request.form.get('member_3')
    m4 = request.form.get('member_4')
    slot_id = request.form.get('slot_id')
    
    if slot_id:
        try:
            slot_res = supabase.table("slots").select("slot_time").eq("id", int(slot_id)).execute()
            if slot_res.data and len(slot_res.data) > 0:
                slot_time_str = slot_res.data[0]['slot_time'].replace('Z', '+00:00')
                slot_time = datetime.fromisoformat(slot_time_str)
                now = datetime.now(timezone.utc)
                time_diff = (slot_time - now).total_seconds() / 60
                if 0 < time_diff <= 20:
                    flash("স্লট ওপেন হতে ২০ মিনিটের কম সময় বাকি! ফাইল আপলোড লক হয়ে গেছে।", "danger")
                    return redirect(url_for('index'))
        except Exception as e:
            print(f"Slot timing check error: {e}")

    file = request.files.get('web_file')
    file_url = "No File Uploaded"
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        file_url = f"Temporary_Storage/{filename}"

    group_data = {
        "group_name": group_name,
        "member_1_name": m1,
        "member_2_name": m2 if m2 else None,
        "member_3_name": m3 if m3 else None,
        "member_4_name": m4 if m4 else None,
        "uploaded_file_url": file_url
    }
    
    try:
        group_res = supabase.table("group_bookings").insert(group_data).execute()
        if group_res.data and len(group_res.data) > 0 and slot_id:
            new_group_id = group_res.data[0]['id']
            supabase.table("slots").update({
                "status": "pending", 
                "booked_by_group_id": int(new_group_id)
            }).eq("id", int(slot_id)).execute()
            flash("গ্রুপ এবং ফাইল সফলভাবে যুক্ত হয়েছে! অনুগ্রহ করে পেমেন্ট সম্পন্ন করুন।", "success")
        else:
            flash("গ্রুপ তৈরি হয়েছে কিন্তু স্লট নির্বাচন করা হয়নি।", "warning")
    except Exception as e:
        flash(f"ডাটাবেজ সাবমিশনে সমস্যা হয়েছে: {str(e)}", "danger")
        
    return redirect(url_for('index'))

@app.route('/submit-payment', methods=['POST'])
def submit_payment():
    if not supabase:
        return redirect(url_for('index'))
    slot_id = request.form.get('slot_id')
    txn_id = request.form.get('txn_id')
    try:
        supabase.table("slots").update({"txn_id": txn_id}).eq("id", int(slot_id)).execute()
        flash("আপনার ট্রানজেকশন আইডি সফলভাবে জমা দেওয়া হয়েছে।", "success")
    except Exception as e:
        flash(f"পেমেন্ট আপডেট ব্যর্থ: {str(e)}", "danger")
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
def admin_dashboard():
    bookings_data = []
    slots_data = []
    if supabase:
        try:
            bookings_res = supabase.table("group_bookings").select("*").execute()
            slots_res = supabase.table("slots").select("*").execute()
            bookings_data = bookings_res.data if bookings_res.data else []
            slots_data = slots_res.data if slots_res.data else []
        except Exception as e:
            print(f"Admin Dashboard error: {e}")
    return render_template('admin.html', bookings=bookings_data, slots=slots_data)

@app.route('/admin/approve-payment/<int:slot_id>', methods=['POST'])
def approve_payment(slot_id):
    if not supabase:
        return redirect(url_for('admin_dashboard'))
    try:
        supabase.table("slots").update({"status": "confirmed"}).eq("id", slot_id).execute()
        flash("বুকিং পেমেন্ট সফলভাবে অনুমোদিত হয়েছে!", "success")
    except Exception as e:
        flash(f"অ্যাপ্রুভ করতে সমস্যা হয়েছে: {str(e)}", "danger")
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

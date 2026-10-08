import os
from flask import Flask, render_template, request, redirect, url_value_preprocessor, flash
from supabase import create_client, Client
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
app.secret_key = "super-secret-key-for-session"

# Supabase কানেকশন সেটআপ (Render Env Vars থেকে রিড করবে)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ফাইল আপলোডের কনফিগারেশন
UPLOAD_FOLDER = '/tmp' # Render-এর সাময়িক লোকাল স্টোরেজ
ALLOWED_EXTENSIONS = {'zip', 'pdf', 'html'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('login.html')

# গ্রুপ তৈরি এবং ফাইল আপলোড লজিক
@app.route('/create-group', methods=['POST'])
def create_group():
    # কারেন্ট টাইম চেক করে স্লট লক লজিক ইমপ্লিমেন্ট করা যায়
    # উদাহরণ: স্লট টাইম যদি রাত ৮টা হয়, তবে তার ২০ মিনিট আগে লক হবে
    
    group_name = request.form.get('group_name')
    m1 = request.form.get('member_1')
    m2 = request.form.get('member_2')
    m3 = request.form.get('member_3')
    m4 = request.form.get('member_4')
    
    file = request.files.get('web_file')
    file_url = ""
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # বাস্তব প্রজেক্টে এই ফাইলটি Cloudinary বা Google Drive-এ আপলোড করা নিরাপদ
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        file_url = f"Local_Temp_Storage/{filename}"

    # Supabase-এ ডেটা সেভ করা
    data = {
        "group_name": group_name,
        "member_1_name": m1,
        "member_2_name": m2,
        "member_3_name": m3,
        "member_4_name": m4,
        "uploaded_file_url": file_url
    }
    
    try:
        supabase.table("group_bookings").insert(data).execute()
        flash("গ্রুপ এবং ফাইল সফলভাবে আপলোড হয়েছে!", "success")
    except Exception as e:
        flash(f"ত্রুটি ঘটেছে: {str(e)}", "danger")
        
    return redirect('/')

# ম্যানুয়াল পেমেন্ট ভেরিফিকেশন (অ্যাডমিন প্যানেল)
@app.route('/admin/dashboard')
def admin_dashboard():
    # ডাটাবেজ থেকে সব বুকিং রিকোয়েস্ট নিয়ে আসা
    bookings = supabase.table("group_bookings").select("*").execute()
    slots_data = supabase.table("slots").select("*").execute()
    return render_template('admin.html', bookings=bookings.data, slots=slots_data.data)

@app.route('/admin/approve-payment/<int:slot_id>', methods=['POST'])
def approve_payment(slot_id):
    # ম্যানুয়াল পেমেন্ট চেক করার পর অ্যাডমিন স্ট্যাটাস কনফার্ম করবেন
    try:
        supabase.table("slots").update({"status": "confirmed"}).eq("id", slot_id).execute()
        flash("পেমেন্ট সফলভাবে ভেরিফাই এবং কনফার্ম করা হয়েছে।", "success")
    except Exception as e:
        flash(f"আপডেট করতে সমস্যা হয়েছে: {str(e)}", "danger")
    return redirect('/admin/dashboard')

if __name__ == '__main__':
    app.run(debug=True)

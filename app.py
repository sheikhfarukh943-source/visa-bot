@app.route("/")
def home():
    # সেশনে ইউজার আইডি না থাকলে সরাসরি লগইন পেজে পাঠিয়ে দেবে
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    # অ্যাডমিন হলে অ্যাডমিন ড্যাশবোর্ডে যাবে
    if session.get('role') == 'Admin':
        return redirect(url_for('admin_dashboard'))
        
    # সাধারণ ইউজার হলে তবেই ফাইল আপলোড পেজ (index.html) দেখতে পাবে
    return render_template("index.html", username=session.get('username'))

import asyncio
import os
import random
from datetime import datetime
from flask import Flask, jsonify, render_template, request
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

app = Flask(__name__)

# সেশন এবং অ্যাডমিন ট্র্যাকিং ডাটাবেজ/মেমরি
active_sessions = {}
admin_stats = {
    "total_uploads": 0,
    "successful_bookings": 0,
    "failed_bookings": 0,
    "history": [] # ফাইল আপলোডের বিস্তারিত তালিকা সংরক্ষণ করার জন্য
}

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PROXY_SERVER = os.getenv("PROXY_URL", "")

async def run_visa_scheduler(session_id, center, passport, phone, file_path, filename):
    async with async_playwright() as p:
        browser_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
        ]
        
        proxy_dict = {"server": PROXY_SERVER} if PROXY_SERVER else None
        browser = await p.chromium.launch(headless=True, args=browser_args, proxy=proxy_dict)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_async(page)

        active_sessions[session_id] = {
            "status": "server_waiting",
            "otp_submitted": asyncio.Event(),
            "otp_code": None,
            "result": None
        }

        # অ্যাডমিন লগ তৈরি
        log_entry = {
            "passport": passport,
            "phone": phone,
            "filename": filename,
            "center": center,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Pending"
        }
        admin_stats["history"].append(log_entry)

        try:
            # ১. আইভ্যাক পোর্টাল ট্রাই লুপ
            while True:
                try:
                    await page.goto("https://ivacbd.com", timeout=20000, wait_until="commit")
                    if await page.query_selector("input[name='passport_number']"):
                        break
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(3.0, 6.0))

            active_sessions[session_id]["status"] = "processing_fields"
            
            # ২. তথ্য পূরণ ও সাবমিট
            await page.fill("input[name='passport_number']", passport)
            await page.fill("input[name='mobile_number']", phone)
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await page.click("#next-step-btn")

            # ৩. ওটিপি পেজ হ্যান্ডলিং
            await page.wait_for_selector("input[name='otp_code_input']", timeout=30000)
            active_sessions[session_id]["status"] = "waiting_for_otp"

            # ওটিপি পাওয়ার জন্য হোল্ড করা
            await active_sessions[session_id]["otp_submitted"].wait()

            # ৪. ওটিপি ইনজেক্ট
            user_otp = active_sessions[session_id]["otp_code"]
            await page.fill("input[name='otp_code_input']", user_otp)
            await page.click("#verify-otp-btn")

            # ৫. প্রিলোড করা ফাইল আপলোড ও সেন্টার সিলেকশন
            await page.wait_for_selector("input[type='file']", timeout=15000)
            await page.set_input_files("input[type='file']", file_path)
            await page.select_option("select[name='visa_center']", label=center)
            await page.click("#confirm-details-btn")

            # ৬. স্লট কনফার্ম ও লিংক ডিটেকশন
            await page.wait_for_selector("#confirm-booking-btn", timeout=15000)
            await page.click("#confirm-booking-btn")

            await page.wait_for_url("**/payment**", timeout=40000)
            payment_url = page.url

            active_sessions[session_id]["result"] = {
                "status": "success",
                "message": "স্লট কনফার্ম হয়েছে!",
                "payment_url": payment_url
            }
            admin_stats["successful_bookings"] += 1
            log_entry["status"] = "Success"
            
            await asyncio.sleep(600) # পেমেন্টের জন্য ১০ মিনিট লাইভ রাখা

        except Exception as e:
            active_sessions[session_id]["result"] = {
                "status": "error",
                "message": f"ব্যর্থ হয়েছে: {str(e)}"
            }
            admin_stats["failed_bookings"] += 1
            log_entry["status"] = f"Failed ({str(e)})"
        finally:
            active_sessions[session_id]["status"] = "completed"
            await browser.close()
            if os.path.exists(file_path):
                os.remove(file_path)


@app.route("/")
def home():
    return render_template("index.html")

# নতুন অ্যাডমিন ড্যাশবোর্ড ভিউ রাউট
@app.route("/admin")
def admin_dashboard():
    return render_template("admin.html")

# অ্যাডমিন স্ট্যাটাস ডেটা পাঠানোর API
@app.route("/admin/stats", methods=["GET"])
def get_admin_stats():
    return jsonify(admin_stats)

@app.route("/pre-load", methods=["POST"])
def pre_load_data():
    center = request.form.get("center")
    passport = request.form.get("passport")
    phone = request.form.get("phone")
    web_file = request.files.get("web_file")

    if not all([center, passport, phone, web_file]):
        return jsonify({"status": "error", "message": "সব তথ্য ও ফাইল দিন"}), 400

    filename = web_file.filename
    file_path = os.path.join(UPLOAD_FOLDER, f"{passport}_{filename}")
    web_file.save(file_path)

    # অ্যাডমিন টোটাল আপলোড কাউন্টার বৃদ্ধি
    admin_stats["total_uploads"] += 1

    asyncio.create_task(run_visa_scheduler(passport, center, passport, phone, file_path, filename))
    return jsonify({"status": "queued", "session_id": passport, "message": "ফাইল আপলোড ট্র্যাক করা হয়েছে এবং বট প্রসেসিং কিউতে আছে।"})

@app.route("/poll-status/<session_id>", methods=["GET"])
def poll_status(session_id):
    session = active_sessions.get(session_id)
    if not session:
        return jsonify({"status": "not_found"})
    return jsonify({"status": session["status"], "result": session.get("result")})

@app.route("/submit-otp", methods=["POST"])
def submit_otp():
    data = request.json
    session = active_sessions.get(data.get("session_id"))
    if session and session["status"] == "waiting_for_otp":
        session["otp_code"] = data.get("otp")
        session["otp_submitted"].set()
        return jsonify({"status": "otp_injected"})
    return jsonify({"status": "error", "message": "সেশন সক্রিয় নেই।"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

import os
import json
import hashlib
import asyncio
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from telethon import TelegramClient, errors

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Telegram API for UserSession
API_ID = 30158256
API_HASH = "547889500d1e8399c3da0a8ecff5f461"

DATA_FILE = 'user_data.json'
SESSIONS_DIR = 'sessions'

if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

# Global dictionary to store pending clients
pending_clients = {}

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def get_user_id_from_login_id(login_id, data):
    """Maps 15-char login ID back to Telegram user ID"""
    for user_id in data:
        expected_login_id = hashlib.md5(str(user_id).encode()).hexdigest()[:15].upper()
        if expected_login_id == login_id:
            return str(user_id)
    return None

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    login_id = request.form.get('user_id', '').strip().upper()
    data = load_data()
    
    # Check if the input is a 15-char MD5-based login ID
    user_id = get_user_id_from_login_id(login_id, data)
    
    # Fallback to direct user_id check (for backward compatibility/admin)
    if not user_id:
        # Check if the login_id matches the admin ID directly
        if login_id == '2876886938':
            user_id = '2876886938'
        elif login_id in data:
            user_id = login_id

    if user_id:
        # In this new flow, we don't set session yet. 
        # We just confirm the ID is valid and then the frontend shows OTP.
        return jsonify({'success': True, 'user_id': user_id})
    
    return jsonify({'success': False, 'message': "Invalid ID"}), 401

@app.route('/request_otp', methods=['POST'])
async def request_otp():
    phone = request.json.get('phone', '').strip()
    if not phone:
        return jsonify({'success': False, 'message': 'Phone number required'}), 400
    
    session_path = os.path.join(SESSIONS_DIR, f"{phone}")
    client = TelegramClient(session_path, API_ID, API_HASH)
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            sent_code = await client.send_code_request(phone)
            pending_clients[phone] = {
                'client': client,
                'phone_code_hash': sent_code.phone_code_hash
            }
            return jsonify({'success': True, 'message': 'OTP sent successfully'})
        else:
            # If already authorized, we still need to know which user_id this is for the session
            # For simplicity, we'll let the frontend handle the dashboard redirect
            await client.disconnect()
            return jsonify({'success': True, 'message': 'Already logged in', 'authorized': True})
    except Exception as e:
        if client.is_connected():
            await client.disconnect()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/verify_otp', methods=['POST'])
async def verify_otp():
    phone = request.json.get('phone', '').strip()
    otp = request.json.get('otp', '').strip()
    user_id = request.json.get('user_id', '').strip() # Passed from frontend
    
    if phone not in pending_clients:
        return jsonify({'success': False, 'message': 'Session expired or not found'}), 400
    
    client_data = pending_clients[phone]
    client = client_data['client']
    phone_code_hash = client_data['phone_code_hash']
    
    try:
        await client.sign_in(phone, otp, phone_code_hash=phone_code_hash)
        # Login successful
        del pending_clients[phone]
        await client.disconnect()
        
        # Now set the flask session
        session['user_id'] = user_id
        return jsonify({'success': True, 'message': 'Login successful'})
    except errors.SessionPasswordNeededError:
        return jsonify({'success': False, 'needs_password': True, 'message': 'Two-step verification enabled'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    data = load_data()
    user_info = data.get(user_id, {})
    
    # Real data from user_data.json
    processing_details = user_info.get('processing_details', [])
    processed_numbers = []
    
    # Add from processing_details (the real source of truth now)
    for item in processing_details:
        status = item.get('status', 'Processing')
        # Filter: Only show if status is one of the valid ones (this handles the "only show when confirmed" logic)
        if status in ['Processing', 'Successful', 'Reject']:
            timestamp_str = item.get('timestamp', '')
            countdown = ""
            if status == 'Processing' and timestamp_str:
                try:
                    start_time = datetime.fromisoformat(timestamp_str)
                    now = datetime.now()
                    elapsed = now - start_time
                    total_allowed = 38 * 3600 # 38 hours
                    
                    # Auto-extension logic: if 30 hours passed, add another 30 hours
                    while elapsed.total_seconds() > total_allowed:
                        total_allowed += 30 * 3600
                    
                    remaining_seconds = total_allowed - elapsed.total_seconds()
                    hours = int(remaining_seconds // 3600)
                    minutes = int((remaining_seconds % 3600) // 60)
                    countdown = f"{hours}h {minutes}m"
                except:
                    countdown = "N/A"

            processed_numbers.append({
                'number': item.get('number', 'N/A'),
                'status': status,
                'price': f"{item.get('price', 0.0):.2f} USD",
                'country': item.get('country', 'N/A'),
                'date': item.get('timestamp', 'N/A').split('T')[0] if 'T' in item.get('timestamp', '') else item.get('timestamp', 'N/A'),
                'raw_timestamp': item.get('timestamp', ''),
                'countdown': countdown
            })
    
    return render_template('dashboard.html', numbers=processed_numbers)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or session['user_id'] != '2876886938':
        return redirect(url_for('index'))
    return render_template('admin.html')

@app.route('/admin/search', methods=['POST'])
def admin_search():
    if 'user_id' not in session or session['user_id'] != '2876886938':
        return redirect(url_for('index'))
    
    search_id = request.form.get('chat_id', '').strip()
    data = load_data()
    user_info = data.get(search_id, {})
    
    processed_numbers = []
    stats = {'processing': 0, 'successful': 0, 'reject': 0}
    
    if user_info:
        processing_details = user_info.get('processing_details', [])
        for item in processing_details:
            status = item.get('status', 'Processing')
            processed_numbers.append({
                'number': item.get('number', 'N/A'),
                'status': status,
                'price': f"{item.get('price', 0.0):.2f} USD",
                'country': item.get('country', 'N/A'),
                'date': item.get('timestamp', 'N/A').split('T')[0] if 'T' in item.get('timestamp', '') else item.get('timestamp', 'N/A')
            })
            
            if status == 'Processing':
                stats['processing'] += 1
            elif status == 'Successful':
                stats['successful'] += 1
            elif status == 'Reject':
                stats['reject'] += 1
    
    return render_template('admin_results.html', numbers=processed_numbers, search_id=search_id, stats=stats)

@app.route('/admin/notify', methods=['POST'])
def admin_notify():
    if 'user_id' not in session or session['user_id'] != '2876886938':
        return redirect(url_for('index'))
    
    notify_type = request.form.get('type', 'all')
    message = request.form.get('message', '').strip()
    chat_id = request.form.get('chat_id', '').strip()
    
    if message:
        queue = []
        if os.path.exists('broadcast_queue.json'):
            try:
                with open('broadcast_queue.json', 'r') as f:
                    queue = json.load(f)
                    if not isinstance(queue, list):
                        queue = []
            except:
                queue = []
        
        notification = {
            'type': notify_type,
            'message': message,
            'chat_id': chat_id if notify_type == 'custom' else None,
            'timestamp': datetime.now().isoformat()
        }
        queue.append(notification)
            
        with open('broadcast_queue.json', 'w') as f:
            json.dump(queue, f)
            
    return redirect(url_for('admin_panel'))

@app.route('/admin/set_link', methods=['POST'])
def admin_set_link():
    if 'user_id' not in session or session['user_id'] != '2876886938':
        return redirect(url_for('index'))
    
    link = request.form.get('dashboard_link', '').strip()
    if link:
        settings = {}
        if os.path.exists('settings.json'):
            with open('settings.json', 'r') as f:
                settings = json.load(f)
        settings['dashboard_link'] = link
        with open('settings.json', 'w') as f:
            json.dump(settings, f)
            
    return redirect(url_for('admin_panel'))

@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session or session['user_id'] != '2876886938':
        return redirect(url_for('index'))
    data = load_data()
    users = []
    for uid, info in data.items():
        users.append({
            'chat_id': uid,
            'balance': info.get('main_balance_usdt', 0.0),
            'sold': info.get('accounts_sold', 0)
        })
    return render_template('admin_list.html', title="User List", items=users, type='users')

@app.route('/admin/processing')
def admin_processing():
    if 'user_id' not in session or session['user_id'] != '2876886938':
        return redirect(url_for('index'))
    data = load_data()
    items = []
    now = datetime.now()
    for uid, info in data.items():
        for detail in info.get('processing_details', []):
            if detail.get('status') == 'Processing':
                ts = detail.get('timestamp', '')
                elapsed_str = "N/A"
                if ts:
                    try:
                        elapsed = now - datetime.fromisoformat(ts)
                        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
                        minutes, seconds = divmod(remainder, 60)
                        elapsed_str = f"{hours}h {minutes}m {seconds}s"
                    except: pass
                items.append({
                    'chat_id': uid,
                    'number': detail.get('number'),
                    'country': detail.get('country'),
                    'time': elapsed_str,
                    'price': detail.get('price', 0.0)
                })
    return render_template('admin_list.html', title="Processing Numbers", items=items, type='processing')

@app.route('/admin/successful')
def admin_successful():
    if 'user_id' not in session or session['user_id'] != '2876886938':
        return redirect(url_for('index'))
    data = load_data()
    items = []
    for uid, info in data.items():
        for detail in info.get('processing_details', []):
            if detail.get('status') == 'Successful':
                items.append({
                    'chat_id': uid,
                    'number': detail.get('number'),
                    'country': detail.get('country'),
                    'price': detail.get('price', 0.0),
                    'date': detail.get('timestamp', '').split('T')[0] if 'T' in detail.get('timestamp', '') else 'N/A'
                })
    return render_template('admin_list.html', title="Successful Numbers", items=items, type='successful')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

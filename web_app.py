import os
import json
import hashlib
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.urandom(24)

DATA_FILE = 'user_data.json'

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
        session['user_id'] = user_id
        return redirect(url_for('dashboard'))
    
    # Return a better looking error page or style the response
    return render_template('login.html', error="Invalid ID. Please check your 'My History' ID in the bot."), 401

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
            processed_numbers.append({
                'number': item.get('number', 'N/A'),
                'status': status,
                'price': f"{item.get('price', 0.0):.2f} USD",
                'country': item.get('country', 'N/A'),
                'date': item.get('timestamp', 'N/A').split('T')[0] if 'T' in item.get('timestamp', '') else item.get('timestamp', 'N/A'),
                'raw_timestamp': item.get('timestamp', '')
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

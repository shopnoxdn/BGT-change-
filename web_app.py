import os
import json
import hashlib
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
    if not user_id and login_id in data:
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
    
    for item in processing_details:
        status = item.get('status', 'Processing')
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

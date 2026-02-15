import os
import json
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.urandom(24)

DATA_FILE = 'user_data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    user_id = request.form.get('user_id')
    data = load_data()
    if user_id in data:
        session['user_id'] = user_id
        return redirect(url_for('dashboard'))
    return "Invalid ID. Please check your 'My History' ID in the bot.", 401

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    data = load_data()
    user_info = data.get(user_id, {})
    
    # Real data from user_data.json
    numbers = user_info.get('sold_numbers', [])
    processed_numbers = []
    for item in numbers:
        if isinstance(item, dict):
            # If item is already a dict, use it but ensure fields exist
            status = item.get('status', 'Processing')
            processed_numbers.append({
                'number': item.get('number', 'N/A'),
                'status': status,
                'price': f"{item.get('price', 0.20):.2f} USD",
                'date': item.get('timestamp', 'N/A').split('T')[0] if 'T' in item.get('timestamp', '') else item.get('timestamp', 'N/A'),
                'raw_timestamp': item.get('timestamp', '')
            })
        elif isinstance(item, str):
            # If item is just a number string
            processed_numbers.append({
                'number': item,
                'status': 'Successful',
                'price': '0.20 USD',
                'date': '2026-02-15',
                'raw_timestamp': ''
            })
            
    return render_template('dashboard.html', numbers=processed_numbers)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

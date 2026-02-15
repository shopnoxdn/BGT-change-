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
    
    # Mocking status for numbers since the original data structure 
    # might not have explicit status per number in the provided snippet.
    # In a real app, 'sold_numbers' would be objects with status.
    numbers = user_info.get('sold_numbers', [])
    processed_numbers = []
    for num in numbers:
        # For demonstration, we'll assign some mock data if it's just a string list
        if isinstance(num, str):
            processed_numbers.append({
                'number': num,
                'status': 'Successful', # Default status
                'price': '0.20 USD',
                'date': '2026-02-15'
            })
        else:
            processed_numbers.append(num)
            
    return render_template('dashboard.html', numbers=processed_numbers)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

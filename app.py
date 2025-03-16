import os
import json
import base64
import pandas as pd
import re
import html
import pickle
import time
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, jsonify
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

app = Flask(__name__)
# Update scopes to include full access
SCOPES = ['https://mail.google.com/']
CACHE_DIR = 'email_cache'
CACHE_EXPIRY = 24  # Cache expiry in hours

# Create cache directory if it doesn't exist
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# Authenticate with Google
def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES
        )
        # Request offline access and force approval prompt to get refresh token
        creds = flow.run_local_server(port=0, access_type='offline')
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

# Extract domain from email address
def extract_domain(email):
    # Match email pattern and extract domain
    match = re.search(r'[\w\.-]+@([\w\.-]+)', email)
    if match:
        return match.group(1)
    # If no email pattern found, try to extract domain from a URL or company name
    match = re.search(r'([\w\.-]+\.(com|org|net|edu|io|co|gov))\b', email)
    if match:
        return match.group(1)
    return "Other"

# Check if cache is valid
def is_cache_valid(cache_file):
    if not os.path.exists(cache_file):
        return False

    # Check if cache is expired
    file_modified_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
    if datetime.now() - file_modified_time > timedelta(hours=CACHE_EXPIRY):
        return False

    return True

# Save emails to cache
def save_to_cache(data, cache_type='list'):
    cache_file = os.path.join(CACHE_DIR, f'{cache_type}_cache.pkl')
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

# Load emails from cache
def load_from_cache(cache_type='list'):
    cache_file = os.path.join(CACHE_DIR, f'{cache_type}_cache.pkl')
    if is_cache_valid(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"Error loading cache: {e}")
    return None

# Fetch emails and classify
@app.route('/')
def index():
    # Try to load from cache first
    cached_data = load_from_cache('list')
    if cached_data:
        # Sort the cached data by number of emails in each domain
        sorted_data = dict(sorted(cached_data.items(),
                                 key=lambda item: len(item[1]),
                                 reverse=True))
        return render_template('index.html', grouped=sorted_data)

    # If no valid cache, fetch from Gmail API
    service = get_gmail_service()
    results = service.users().messages().list(userId='me', maxResults=50).execute()
    messages = results.get('messages', [])
    email_data = []

    for msg in messages:
        msg_detail = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = msg_detail['payload']['headers']
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
        date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        domain = extract_domain(sender)
        email_data.append({
            'id': msg['id'],
            'sender': sender,
            'subject': subject,
            'date': date,
            'domain': domain
        })

    df = pd.DataFrame(email_data)
    # Group by domain instead of category
    grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records')).to_dict()

    # Sort the grouped data by number of emails in each domain
    sorted_grouped = dict(sorted(grouped.items(),
                                key=lambda item: len(item[1]),
                                reverse=True))

    # Save to cache
    save_to_cache(sorted_grouped, 'list')

    return render_template('index.html', grouped=sorted_grouped)

# Get email content for preview
@app.route('/email/<email_id>', methods=['GET'])
def get_email(email_id):
    # Try to load from cache first
    cache_file = os.path.join(CACHE_DIR, f'email_{email_id}.pkl')
    if is_cache_valid(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                return jsonify(pickle.load(f))
        except Exception as e:
            print(f"Error loading email cache: {e}")

    # If no valid cache, fetch from Gmail API
    service = get_gmail_service()
    msg = service.users().messages().get(userId='me', id=email_id, format='full').execute()

    # Extract headers
    headers = msg['payload']['headers']
    sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
    date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
    to = next((h['value'] for h in headers if h['name'] == 'To'), '')

    # Extract body
    body = ""
    if 'parts' in msg['payload']:
        for part in msg['payload']['parts']:
            if part['mimeType'] == 'text/plain' or part['mimeType'] == 'text/html':
                if 'data' in part['body']:
                    body_data = part['body']['data']
                    body = base64.urlsafe_b64decode(body_data).decode('utf-8')
                    break
    elif 'body' in msg['payload'] and 'data' in msg['payload']['body']:
        body_data = msg['payload']['body']['data']
        body = base64.urlsafe_b64decode(body_data).decode('utf-8')

    # If body is HTML, keep it as is, otherwise escape it and add line breaks
    if not body.strip().startswith('<'):
        body = html.escape(body).replace('\n', '<br>')
        body = f'<div style="font-family: monospace; white-space: pre-wrap;">{body}</div>'

    email_data = {
        'id': email_id,
        'sender': sender,
        'to': to,
        'subject': subject,
        'date': date,
        'body': body
    }

    # Save to cache
    with open(cache_file, 'wb') as f:
        pickle.dump(email_data, f)

    return jsonify(email_data)

# Handle actions
@app.route('/action', methods=['POST'])
def action():
    service = get_gmail_service()
    email_ids = request.form.getlist('email_ids')
    action_type = request.form['action_type']

    for email_id in email_ids:
        if action_type == 'read':
            service.users().messages().modify(userId='me', id=email_id, body={'removeLabelIds': ['UNREAD']}).execute()
        elif action_type == 'delete':
            service.users().messages().delete(userId='me', id=email_id).execute()
            # Remove from cache if deleted
            cache_file = os.path.join(CACHE_DIR, f'email_{email_id}.pkl')
            if os.path.exists(cache_file):
                os.remove(cache_file)
        elif action_type == 'archive':
            service.users().messages().modify(userId='me', id=email_id, body={'removeLabelIds': ['INBOX']}).execute()

    # Clear the list cache since the email list has changed
    list_cache = os.path.join(CACHE_DIR, 'list_cache.pkl')
    if os.path.exists(list_cache):
        os.remove(list_cache)

    return redirect('/')

# Clear cache route
@app.route('/clear-cache', methods=['GET'])
def clear_cache():
    for file in os.listdir(CACHE_DIR):
        os.remove(os.path.join(CACHE_DIR, file))
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)

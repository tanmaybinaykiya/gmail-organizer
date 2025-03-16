import os
import json
import base64
import pandas as pd
import re
import html
import pickle
import time
import threading
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
MAX_EMAILS_PER_PAGE = 100  # Maximum number of emails to fetch per page (reduced for faster initial load)
MAX_TOTAL_EMAILS = 10000  # Maximum total emails to fetch

# Create cache directory if it doesn't exist
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# Global variables to track fetching status
fetch_status = {
    'is_fetching': False,
    'total_emails': 0,
    'fetched_emails': 0,
    'next_page_token': None,
    'grouped_emails': {},
    'error': None,
    'is_paused': False,  # New flag to track if fetching is paused
    'last_fetch_time': None  # Track when the last fetch occurred
}

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

# Save pagination state
def save_pagination_state(next_page_token, fetched_count, total_count):
    state = {
        'next_page_token': next_page_token,
        'fetched_count': fetched_count,
        'total_count': total_count,
        'timestamp': datetime.now().timestamp()
    }
    with open(os.path.join(CACHE_DIR, 'pagination_state.json'), 'w') as f:
        json.dump(state, f)

# Load pagination state
def load_pagination_state():
    state_file = os.path.join(CACHE_DIR, 'pagination_state.json')
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)

            # Check if state is still valid (less than 1 hour old)
            if datetime.now().timestamp() - state.get('timestamp', 0) < 3600:
                return state
        except Exception as e:
            print(f"Error loading pagination state: {e}")
    return None

# Fetch a batch of emails
def fetch_email_batch(page_token=None):
    service = get_gmail_service()

    # Get total unread count if we don't have it yet
    if fetch_status['total_emails'] == 0:
        result = service.users().messages().list(
            userId='me',
            q='is:unread',
            maxResults=1
        ).execute()
        fetch_status['total_emails'] = result.get('resultSizeEstimate', 0)

    # Fetch a page of messages
    results = service.users().messages().list(
        userId='me',
        q='is:unread',
        maxResults=MAX_EMAILS_PER_PAGE,
        pageToken=page_token
    ).execute()

    messages = results.get('messages', [])
    email_data = []

    # Process each message in the current page
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

    # Get next page token
    next_page_token = results.get('nextPageToken')

    return email_data, next_page_token

# Sort grouped emails by count
def sort_grouped_emails(grouped_emails):
    return dict(sorted(grouped_emails.items(), key=lambda item: len(item[1]), reverse=True))

# Background task to fetch emails
def fetch_emails_background():
    global fetch_status
    try:
        # Set last fetch time
        fetch_status['last_fetch_time'] = datetime.now()

        # Load existing emails from cache
        cached_data = load_from_cache('list')
        if cached_data and isinstance(cached_data, dict) and 'grouped' in cached_data:
            email_data = []
            for domain, emails in cached_data['grouped'].items():
                email_data.extend(emails)

            # Update fetch status with cached data
            fetch_status['fetched_emails'] = len(email_data)
            fetch_status['grouped_emails'] = cached_data['grouped']

            # Load pagination state
            pagination_state = load_pagination_state()
            if pagination_state:
                fetch_status['next_page_token'] = pagination_state.get('next_page_token')
                fetch_status['total_emails'] = pagination_state.get('total_count', 0)
        else:
            email_data = []

        # Continue fetching from where we left off
        next_page_token = fetch_status['next_page_token']

        while len(email_data) < MAX_TOTAL_EMAILS:
            # Check if fetching is paused
            if fetch_status['is_paused']:
                # Save current state to cache before pausing
                if email_data:
                    df = pd.DataFrame(email_data)
                    if not df.empty:
                        grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records'), include_groups=False).to_dict()
                        sorted_grouped = sort_grouped_emails(grouped)
                        fetch_status['grouped_emails'] = sorted_grouped

                        # Save to cache
                        cache_data = {
                            'grouped': sorted_grouped,
                            'total_unread': fetch_status['total_emails']
                        }
                        save_to_cache(cache_data, 'list')

                        # Save pagination state
                        save_pagination_state(next_page_token, len(email_data), fetch_status['total_emails'])

                # Set is_fetching to false while paused
                fetch_status['is_fetching'] = False
                print("Email fetching paused")

                # Exit the fetch loop
                break

            # Fetch a batch of emails
            new_emails, next_page_token = fetch_email_batch(next_page_token)

            if not new_emails:
                break  # No more emails to fetch

            # Add new emails to the list
            email_data.extend(new_emails)

            # Update fetch status
            fetch_status['fetched_emails'] = len(email_data)
            fetch_status['next_page_token'] = next_page_token
            fetch_status['last_fetch_time'] = datetime.now()

            # Save pagination state
            save_pagination_state(next_page_token, len(email_data), fetch_status['total_emails'])

            # Process and update grouped emails
            df = pd.DataFrame(email_data)
            if not df.empty:
                grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records'), include_groups=False).to_dict()
                sorted_grouped = sort_grouped_emails(grouped)
                fetch_status['grouped_emails'] = sorted_grouped

                # Save to cache
                cache_data = {
                    'grouped': sorted_grouped,
                    'total_unread': fetch_status['total_emails']
                }
                save_to_cache(cache_data, 'list')

            # If no more pages, break
            if not next_page_token:
                break

            # If we've fetched enough emails, stop
            if len(email_data) >= MAX_TOTAL_EMAILS:
                break

            # Small delay to prevent API rate limiting
            time.sleep(0.5)

        # Final update to cache
        if email_data and not fetch_status['is_paused']:
            df = pd.DataFrame(email_data)
            if not df.empty:
                grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records'), include_groups=False).to_dict()
                sorted_grouped = sort_grouped_emails(grouped)
            else:
                sorted_grouped = {}

            cache_data = {
                'grouped': sorted_grouped,
                'total_unread': fetch_status['total_emails']
            }
            save_to_cache(cache_data, 'list')
            fetch_status['grouped_emails'] = sorted_grouped

            # Only set is_fetching to False if not paused (if paused, we already set it above)
            if not fetch_status['is_paused']:
                fetch_status['is_fetching'] = False
                print("Email fetching completed")

    except Exception as e:
        print(f"Error fetching emails: {e}")
        fetch_status['error'] = str(e)
        fetch_status['is_fetching'] = False

# Fetch emails and classify
@app.route('/')
def index():
    global fetch_status

    # Try to load from cache first
    cached_data = load_from_cache('list')
    initial_data = None

    if cached_data and isinstance(cached_data, dict) and 'grouped' in cached_data and 'total_unread' in cached_data:
        # Use cached data for initial render
        initial_data = sort_grouped_emails(cached_data['grouped'])
        total_unread = cached_data['total_unread']

        # Start background fetching to update cache
        if not fetch_status['is_fetching']:
            fetch_status['is_fetching'] = True
            fetch_status['grouped_emails'] = initial_data
            fetch_status['total_emails'] = total_unread
            fetch_status['fetched_emails'] = sum(len(emails) for emails in initial_data.values())

            thread = threading.Thread(target=fetch_emails_background)
            thread.daemon = True
            thread.start()

        return render_template('index.html',
                              grouped=initial_data,
                              total_unread=total_unread,
                              fetched_emails=fetch_status['fetched_emails'],
                              is_loading=fetch_status['is_fetching'])
    else:
        # If no cache, fetch first batch synchronously for immediate display
        try:
            email_data, next_page_token = fetch_email_batch()
            fetch_status['next_page_token'] = next_page_token

            if email_data:
                df = pd.DataFrame(email_data)
                grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records'), include_groups=False).to_dict()
                initial_data = sort_grouped_emails(grouped)
                fetch_status['grouped_emails'] = initial_data
                fetch_status['fetched_emails'] = len(email_data)

                # Save to cache
                cache_data = {
                    'grouped': initial_data,
                    'total_unread': fetch_status['total_emails']
                }
                save_to_cache(cache_data, 'list')

                # Save pagination state
                save_pagination_state(next_page_token, len(email_data), fetch_status['total_emails'])
            else:
                initial_data = {}

            total_unread = fetch_status['total_emails']
        except Exception as e:
            print(f"Error fetching initial emails: {e}")
            initial_data = {}
            total_unread = 0

    # Start background fetching if not already running
    if not fetch_status['is_fetching']:
        fetch_status['is_fetching'] = True
        thread = threading.Thread(target=fetch_emails_background)
        thread.daemon = True
        thread.start()

    # Render the template with whatever data we have
    return render_template('index.html',
                          grouped=initial_data or {},
                          total_unread=total_unread,
                          fetched_emails=fetch_status['fetched_emails'],
                          is_loading=fetch_status['is_fetching'])

# Route to check fetch status and get new emails
@app.route('/fetch-status')
def check_fetch_status():
    global fetch_status

    if fetch_status['error']:
        # Error occurred
        return jsonify({
            'status': 'error',
            'error': fetch_status['error']
        })
    else:
        # Return current status and data
        status = 'paused' if fetch_status['is_paused'] else ('fetching' if fetch_status['is_fetching'] else 'complete')

        # Format last fetch time if available
        last_fetch_time = None
        if fetch_status['last_fetch_time']:
            last_fetch_time = fetch_status['last_fetch_time'].strftime('%Y-%m-%d %H:%M:%S')

        return jsonify({
            'status': status,
            'fetched': fetch_status['fetched_emails'],
            'total': fetch_status['total_emails'],
            'grouped': fetch_status['grouped_emails'],
            'last_fetch_time': last_fetch_time
        })

# Add a route for incremental fetching
@app.route('/fetch-more', methods=['GET'])
def fetch_more():
    page_token = request.args.get('page_token', None)
    current_count = int(request.args.get('current_count', 0))

    service = get_gmail_service()

    # Fetch the next page of messages
    results = service.users().messages().list(
        userId='me',
        q='is:unread',
        maxResults=MAX_EMAILS_PER_PAGE,
        pageToken=page_token
    ).execute()

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

    # Process the new data
    df = pd.DataFrame(email_data)
    if not df.empty:
        grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records'), include_groups=False).to_dict()
    else:
        grouped = {}

    next_page_token = results.get('nextPageToken')

    # Save pagination state
    total_fetched = current_count + len(email_data)
    save_pagination_state(next_page_token, total_fetched, fetch_status['total_emails'])

    return jsonify({
        'emails': grouped,
        'next_page_token': next_page_token,
        'count': len(email_data),
        'total_fetched': total_fetched
    })

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

    # Clear pagination state
    pagination_file = os.path.join(CACHE_DIR, 'pagination_state.json')
    if os.path.exists(pagination_file):
        os.remove(pagination_file)

    return redirect('/')

# Clear cache route
@app.route('/clear-cache', methods=['GET'])
def clear_cache():
    for file in os.listdir(CACHE_DIR):
        os.remove(os.path.join(CACHE_DIR, file))
    return redirect('/')

# Pause email fetching
@app.route('/pause-fetch', methods=['POST'])
def pause_fetch():
    global fetch_status

    fetch_status['is_paused'] = True
    print("Pausing email fetch process")

    return jsonify({
        'status': 'paused',
        'message': 'Email fetching paused'
    })

# Resume email fetching
@app.route('/resume-fetch', methods=['POST'])
def resume_fetch():
    global fetch_status

    # Only start a new thread if we're actually paused
    if fetch_status['is_paused']:
        fetch_status['is_paused'] = False
        fetch_status['is_fetching'] = True
        print("Resuming email fetch process")

        thread = threading.Thread(target=fetch_emails_background)
        thread.daemon = True
        thread.start()

        return jsonify({
            'status': 'fetching',
            'message': 'Email fetching resumed'
        })
    else:
        return jsonify({
            'status': 'error',
            'message': 'Email fetching was not paused'
        })

# Add a route for logging
@app.route('/fetch-logs')
def fetch_logs():
    global fetch_status

    logs = {
        'status': 'paused' if fetch_status['is_paused'] else ('fetching' if fetch_status['is_fetching'] else 'complete'),
        'fetched': fetch_status['fetched_emails'],
        'total': fetch_status['total_emails'],
        'last_fetch_time': fetch_status['last_fetch_time'].strftime('%Y-%m-%d %H:%M:%S') if fetch_status['last_fetch_time'] else None,
        'error': fetch_status['error']
    }

    return jsonify(logs)

if __name__ == '__main__':
    app.run(debug=True)

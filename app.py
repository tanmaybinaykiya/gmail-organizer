import os
import json
import base64
import pandas as pd
import re
import html
import pickle
import time
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, jsonify
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gmail_organizer.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('gmail_organizer')

app = Flask(__name__)
# Add min function to Jinja environment
app.jinja_env.globals.update(min=min)

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
    logger.info("Authenticating with Google")
    creds = None
    if os.path.exists("token.json"):
        logger.info("Found existing token.json file")
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        logger.info("No valid credentials found, initiating OAuth flow")
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES
        )
        # Request offline access and force approval prompt to get refresh token
        creds = flow.run_local_server(port=0, access_type='offline')
        with open("token.json", "w") as token:
            token.write(creds.to_json())
        logger.info("New credentials obtained and saved to token.json")

    logger.info("Building Gmail API service")
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
        logger.debug(f"Cache file {cache_file} does not exist")
        return False

    # Check if cache is expired
    file_modified_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
    if datetime.now() - file_modified_time > timedelta(hours=CACHE_EXPIRY):
        logger.debug(f"Cache file {cache_file} is expired (older than {CACHE_EXPIRY} hours)")
        return False

    logger.debug(f"Cache file {cache_file} is valid")
    return True

# Save emails to cache
def save_to_cache(data, cache_type='list'):
    cache_file = os.path.join(CACHE_DIR, f'{cache_type}_cache.pkl')
    logger.debug(f"Saving data to cache file {cache_file}")
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(data, f)
        logger.debug(f"Successfully saved data to cache file {cache_file}")
    except Exception as e:
        logger.error(f"Error saving to cache file {cache_file}: {e}", exc_info=True)

# Load emails from cache
def load_from_cache(cache_type='list'):
    cache_file = os.path.join(CACHE_DIR, f'{cache_type}_cache.pkl')
    logger.debug(f"Attempting to load data from cache file {cache_file}")
    if is_cache_valid(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            logger.debug(f"Successfully loaded data from cache file {cache_file}")
            return data
        except Exception as e:
            logger.error(f"Error loading cache from {cache_file}: {e}", exc_info=True)
    return None

# Save pagination state
def save_pagination_state(next_page_token, fetched_count, total_count):
    state = {
        'next_page_token': next_page_token,
        'fetched_count': fetched_count,
        'total_count': total_count,
        'timestamp': datetime.now().timestamp()
    }
    state_file = os.path.join(CACHE_DIR, 'pagination_state.json')
    logger.debug(f"Saving pagination state to {state_file}: {state}")
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f)
        logger.debug(f"Successfully saved pagination state to {state_file}")
    except Exception as e:
        logger.error(f"Error saving pagination state to {state_file}: {e}", exc_info=True)

# Load pagination state
def load_pagination_state():
    state_file = os.path.join(CACHE_DIR, 'pagination_state.json')
    logger.debug(f"Attempting to load pagination state from {state_file}")
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)

            # Check if state is still valid (less than 1 hour old)
            if datetime.now().timestamp() - state.get('timestamp', 0) < 3600:
                logger.debug(f"Successfully loaded valid pagination state from {state_file}")
                return state
            else:
                logger.debug(f"Pagination state from {state_file} is expired")
        except Exception as e:
            logger.error(f"Error loading pagination state from {state_file}: {e}", exc_info=True)
    return None

# Fetch a batch of emails
def fetch_email_batch(page_token=None):
    service = get_gmail_service()

    # We won't rely on the API's resultSizeEstimate as it seems inaccurate
    # Instead, we'll count the actual emails we fetch
    logger.info(f"Fetching batch of emails with page token: {page_token}")
    results = service.users().messages().list(
        userId='me',
        q='is:unread',
        maxResults=MAX_EMAILS_PER_PAGE,
        pageToken=page_token
    ).execute()

    messages = results.get('messages', [])
    logger.info(f"Fetched {len(messages)} messages in this batch")

    # If this is the first batch and we don't have a total count yet,
    # set a reasonable initial estimate based on what we've fetched
    if fetch_status['total_emails'] == 0 and messages:
        # If we got a full page, there are likely more emails
        if len(messages) == MAX_EMAILS_PER_PAGE:
            # Set an initial estimate that's higher than what we've fetched
            # We'll adjust this as we fetch more
            fetch_status['total_emails'] = len(messages) * 3  # Arbitrary multiplier
            logger.info(f"Setting initial total email estimate to {fetch_status['total_emails']}")
        else:
            # If we got less than a full page, this is likely all the emails
            fetch_status['total_emails'] = len(messages)
            logger.info(f"Setting total email count to {len(messages)} based on first batch")

    email_data = []

    # Process each message in the current page
    for msg in messages:
        logger.debug(f"Fetching details for message ID: {msg['id']}")
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
    logger.info(f"Next page token: {next_page_token}")

    # If we have no next page token and we're still using our initial estimate,
    # update the total count to match what we've actually fetched
    if not next_page_token and fetch_status['fetched_emails'] > 0:
        # Update total to match what we've actually fetched
        new_total = fetch_status['fetched_emails'] + len(email_data)
        if new_total != fetch_status['total_emails']:
            logger.info(f"Updating total email count from {fetch_status['total_emails']} to {new_total} based on actual fetched emails")
            fetch_status['total_emails'] = new_total

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
        logger.info("Starting background email fetch process")

        # Load existing emails from cache
        cached_data = load_from_cache('list')
        if cached_data and isinstance(cached_data, dict) and 'grouped' in cached_data:
            email_data = []
            for domain, emails in cached_data['grouped'].items():
                email_data.extend(emails)

            # Update fetch status with cached data
            fetch_status['fetched_emails'] = len(email_data)
            fetch_status['grouped_emails'] = cached_data['grouped']
            logger.info(f"Loaded {len(email_data)} emails from cache")

            # Load pagination state
            pagination_state = load_pagination_state()
            if pagination_state:
                fetch_status['next_page_token'] = pagination_state.get('next_page_token')
                # Use the fetched count as our total if we have it
                if pagination_state.get('fetched_count', 0) > 0:
                    fetch_status['total_emails'] = pagination_state.get('fetched_count')
                else:
                    fetch_status['total_emails'] = pagination_state.get('total_count', 0)
                logger.info(f"Loaded pagination state: next_page_token={fetch_status['next_page_token']}, total_emails={fetch_status['total_emails']}")
        else:
            email_data = []
            logger.info("No valid cache found, starting fresh fetch")

        # Continue fetching from where we left off
        next_page_token = fetch_status['next_page_token']

        while len(email_data) < MAX_TOTAL_EMAILS:
            # Check if fetching is paused
            if fetch_status['is_paused']:
                # Save current state to cache before pausing
                if email_data:
                    logger.info(f"Pausing fetch with {len(email_data)} emails fetched so far. Saving to cache.")
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
                logger.info("Email fetching paused")

                # Exit the fetch loop
                break

            # Fetch a batch of emails
            logger.info(f"Fetching next batch of emails with token: {next_page_token}")
            new_emails, next_page_token = fetch_email_batch(next_page_token)

            if not new_emails:
                logger.info("No more emails to fetch")
                break  # No more emails to fetch

            # Add new emails to the list
            email_data.extend(new_emails)
            logger.info(f"Added {len(new_emails)} new emails. Total fetched: {len(email_data)}")

            # Update fetch status
            fetch_status['fetched_emails'] = len(email_data)
            fetch_status['next_page_token'] = next_page_token
            fetch_status['last_fetch_time'] = datetime.now()

            # If we don't have a next page token, we've fetched all emails
            # Update the total count to match what we've actually fetched
            if not next_page_token:
                fetch_status['total_emails'] = len(email_data)
                logger.info(f"No more pages, setting total email count to {len(email_data)}")

            # Save pagination state
            save_pagination_state(next_page_token, len(email_data), fetch_status['total_emails'])
            logger.info(f"Updated pagination state: next_page_token={next_page_token}, fetched_emails={len(email_data)}")

            # Process and update grouped emails
            df = pd.DataFrame(email_data)
            if not df.empty:
                grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records'), include_groups=False).to_dict()
                sorted_grouped = sort_grouped_emails(grouped)
                fetch_status['grouped_emails'] = sorted_grouped
                logger.info(f"Grouped emails by domain. Found {len(sorted_grouped)} domains.")

                # Save to cache
                cache_data = {
                    'grouped': sorted_grouped,
                    'total_unread': fetch_status['total_emails']
                }
                save_to_cache(cache_data, 'list')
                logger.info("Saved grouped emails to cache")

            # If no more pages, break
            if not next_page_token:
                logger.info("No next page token, fetch complete")
                break

            # If we've fetched enough emails, stop
            if len(email_data) >= MAX_TOTAL_EMAILS:
                logger.info(f"Reached maximum email limit ({MAX_TOTAL_EMAILS}), stopping fetch")
                break

            # Small delay to prevent API rate limiting
            time.sleep(0.5)

        # Final update to cache
        if email_data and not fetch_status['is_paused']:
            logger.info("Performing final cache update")
            df = pd.DataFrame(email_data)
            if not df.empty:
                grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records'), include_groups=False).to_dict()
                sorted_grouped = sort_grouped_emails(grouped)
            else:
                sorted_grouped = {}

            # Update total emails to match what we've actually fetched
            fetch_status['total_emails'] = len(email_data)
            logger.info(f"Final update: setting total email count to {len(email_data)}")

            cache_data = {
                'grouped': sorted_grouped,
                'total_unread': fetch_status['total_emails']
            }
            save_to_cache(cache_data, 'list')
            fetch_status['grouped_emails'] = sorted_grouped

            # Only set is_fetching to False if not paused (if paused, we already set it above)
            if not fetch_status['is_paused']:
                fetch_status['is_fetching'] = False
                logger.info("Email fetching completed")

    except Exception as e:
        logger.error(f"Error fetching emails: {e}", exc_info=True)
        fetch_status['error'] = str(e)
        fetch_status['is_fetching'] = False

# Fetch emails and classify
@app.route('/')
def index():
    global fetch_status
    logger.info("Index page requested")

    # Try to load from cache first
    cached_data = load_from_cache('list')
    initial_data = None

    if cached_data and isinstance(cached_data, dict) and 'grouped' in cached_data and 'total_unread' in cached_data:
        # Use cached data for initial render
        initial_data = sort_grouped_emails(cached_data['grouped'])
        total_unread = cached_data['total_unread']
        logger.info(f"Loaded cached data with {total_unread} total unread emails across {len(initial_data)} domains")

        # Start background fetching to update cache
        if not fetch_status['is_fetching']:
            fetch_status['is_fetching'] = True
            fetch_status['grouped_emails'] = initial_data
            fetch_status['total_emails'] = total_unread
            fetch_status['fetched_emails'] = sum(len(emails) for emails in initial_data.values())
            logger.info(f"Starting background fetch with {fetch_status['fetched_emails']} emails already cached")

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
        logger.info("No valid cache found, fetching initial batch synchronously")
        try:
            email_data, next_page_token = fetch_email_batch()
            fetch_status['next_page_token'] = next_page_token

            if email_data:
                logger.info(f"Fetched initial batch with {len(email_data)} emails")
                df = pd.DataFrame(email_data)
                grouped = df.groupby('domain').apply(lambda x: x.to_dict(orient='records'), include_groups=False).to_dict()
                initial_data = sort_grouped_emails(grouped)
                fetch_status['grouped_emails'] = initial_data
                fetch_status['fetched_emails'] = len(email_data)
                logger.info(f"Grouped initial emails into {len(initial_data)} domains")

                # Save to cache
                cache_data = {
                    'grouped': initial_data,
                    'total_unread': fetch_status['total_emails']
                }
                save_to_cache(cache_data, 'list')
                logger.info("Saved initial data to cache")

                # Save pagination state
                save_pagination_state(next_page_token, len(email_data), fetch_status['total_emails'])
                logger.info(f"Saved pagination state with next_page_token={next_page_token}")
            else:
                initial_data = {}
                logger.info("No emails found in initial fetch")

            total_unread = fetch_status['total_emails']
        except Exception as e:
            logger.error(f"Error fetching initial emails: {e}", exc_info=True)
            initial_data = {}
            total_unread = 0

    # Start background fetching if not already running
    if not fetch_status['is_fetching']:
        fetch_status['is_fetching'] = True
        logger.info("Starting background fetch process")
        thread = threading.Thread(target=fetch_emails_background)
        thread.daemon = True
        thread.start()

    # Render the template with whatever data we have
    logger.info(f"Rendering index template with {total_unread} total emails, {len(initial_data or {})} domains")
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
    logger.info(f"Fetch more requested with page_token={page_token}, current_count={current_count}")

    service = get_gmail_service()

    # Fetch the next page of messages
    logger.info("Fetching next page of messages")
    results = service.users().messages().list(
        userId='me',
        q='is:unread',
        maxResults=MAX_EMAILS_PER_PAGE,
        pageToken=page_token
    ).execute()

    messages = results.get('messages', [])
    logger.info(f"Fetched {len(messages)} messages in this batch")
    email_data = []

    for msg in messages:
        logger.debug(f"Fetching details for message ID: {msg['id']}")
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
        logger.info(f"Grouped {len(email_data)} emails into {len(grouped)} domains")
    else:
        grouped = {}
        logger.info("No emails to group in this batch")

    next_page_token = results.get('nextPageToken')
    logger.info(f"Next page token: {next_page_token}")

    # Save pagination state
    total_fetched = current_count + len(email_data)
    save_pagination_state(next_page_token, total_fetched, fetch_status['total_emails'])
    logger.info(f"Updated pagination state: total_fetched={total_fetched}")

    return jsonify({
        'emails': grouped,
        'next_page_token': next_page_token,
        'count': len(email_data),
        'total_fetched': total_fetched
    })

# Get email content for preview
@app.route('/email/<email_id>', methods=['GET'])
def get_email(email_id):
    logger.info(f"Fetching email content for ID: {email_id}")
    # Try to load from cache first
    cache_file = os.path.join(CACHE_DIR, f'email_{email_id}.pkl')
    if is_cache_valid(cache_file):
        try:
            logger.info(f"Loading email {email_id} from cache")
            with open(cache_file, 'rb') as f:
                return jsonify(pickle.load(f))
        except Exception as e:
            logger.error(f"Error loading email cache: {e}", exc_info=True)

    # If no valid cache, fetch from Gmail API
    logger.info(f"Fetching email {email_id} from Gmail API")
    service = get_gmail_service()
    msg = service.users().messages().get(userId='me', id=email_id, format='full').execute()
    logger.info(f"Successfully fetched email {email_id} from API")

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
    logger.info(f"Saving email {email_id} to cache")
    with open(cache_file, 'wb') as f:
        pickle.dump(email_data, f)

    return jsonify(email_data)

# Handle actions
@app.route('/action', methods=['POST'])
def action():
    service = get_gmail_service()
    email_ids = request.form.getlist('email_ids')
    action_type = request.form['action_type']

    logger.info(f"Performing {action_type} action on {len(email_ids)} emails")

    for email_id in email_ids:
        try:
            if action_type == 'read':
                logger.info(f"Marking email {email_id} as read")
                result = service.users().messages().modify(
                    userId='me',
                    id=email_id,
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()
                logger.info(f"Successfully marked email {email_id} as read. Result: {result}")

            elif action_type == 'delete':
                logger.info(f"Moving email {email_id} to trash")
                # First get the email details for logging purposes
                try:
                    email_details = service.users().messages().get(
                        userId='me',
                        id=email_id,
                        format='metadata',
                        metadataHeaders=['Subject', 'From']
                    ).execute()

                    headers = email_details.get('payload', {}).get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
                    sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
                    logger.info(f"About to move email to trash - ID: {email_id}, Subject: {subject}, From: {sender}")
                except Exception as e:
                    logger.warning(f"Could not fetch email details before moving to trash: {e}")

                # Move the email to trash instead of permanently deleting it
                result = service.users().messages().trash(userId='me', id=email_id).execute()
                logger.info(f"Successfully moved email {email_id} to trash. Result: {result}")

                # Remove from cache if moved to trash
                cache_file = os.path.join(CACHE_DIR, f'email_{email_id}.pkl')
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                    logger.info(f"Removed email {email_id} from cache")

            elif action_type == 'archive':
                logger.info(f"Archiving email {email_id}")
                result = service.users().messages().modify(
                    userId='me',
                    id=email_id,
                    body={'removeLabelIds': ['INBOX']}
                ).execute()
                logger.info(f"Successfully archived email {email_id}. Result: {result}")
        except Exception as e:
            logger.error(f"Error performing {action_type} action on email {email_id}: {e}", exc_info=True)

    # Clear the list cache since the email list has changed
    list_cache = os.path.join(CACHE_DIR, 'list_cache.pkl')
    if os.path.exists(list_cache):
        os.remove(list_cache)
        logger.info("Cleared list cache after performing actions")

    # Clear pagination state
    pagination_file = os.path.join(CACHE_DIR, 'pagination_state.json')
    if os.path.exists(pagination_file):
        os.remove(pagination_file)
        logger.info("Cleared pagination state after performing actions")

    return redirect('/')

# Pause email fetching
@app.route('/pause-fetch', methods=['POST'])
def pause_fetch():
    global fetch_status

    fetch_status['is_paused'] = True
    logger.info("Pausing email fetch process via API endpoint")

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
        logger.info("Resuming email fetch process via API endpoint")

        thread = threading.Thread(target=fetch_emails_background)
        thread.daemon = True
        thread.start()

        return jsonify({
            'status': 'fetching',
            'message': 'Email fetching resumed'
        })
    else:
        logger.warning("Attempted to resume fetch process that was not paused")
        return jsonify({
            'status': 'error',
            'message': 'Email fetching was not paused'
        })

# Add a route for logging
@app.route('/fetch-logs')
def fetch_logs():
    global fetch_status

    status = 'paused' if fetch_status['is_paused'] else ('fetching' if fetch_status['is_fetching'] else 'complete')
    last_fetch_time_str = fetch_status['last_fetch_time'].strftime('%Y-%m-%d %H:%M:%S') if fetch_status['last_fetch_time'] else None

    logs = {
        'status': status,
        'fetched': fetch_status['fetched_emails'],
        'total': fetch_status['total_emails'],
        'last_fetch_time': last_fetch_time_str,
        'error': fetch_status['error']
    }

    logger.info(f"Fetch logs requested: {logs}")
    return jsonify(logs)

# Clear cache route
@app.route('/clear-cache', methods=['GET'])
def clear_cache():
    logger.info("Clearing all cache files")
    count = 0
    for file in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, file)
        try:
            os.remove(file_path)
            count += 1
        except Exception as e:
            logger.error(f"Error removing cache file {file_path}: {e}")

    logger.info(f"Cleared {count} cache files")
    return redirect('/')

if __name__ == '__main__':
    logger.info("=== Gmail Organizer starting up ===")
    logger.info(f"Cache directory: {CACHE_DIR}")
    logger.info(f"Max emails per page: {MAX_EMAILS_PER_PAGE}")
    logger.info(f"Max total emails: {MAX_TOTAL_EMAILS}")
    logger.info(f"Cache expiry: {CACHE_EXPIRY} hours")
    app.run(debug=True)

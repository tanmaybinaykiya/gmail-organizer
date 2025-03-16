# Gmail Organizer

A Flask-based web application to organize and manage your Gmail inbox efficiently.

## Features

- Group emails by domain for better organization
- Preview email content without leaving the application
- Perform bulk actions (delete, archive, mark as read) on selected emails
- Caching system to reduce API calls and improve performance
- Responsive design that works on both desktop and mobile

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/tanmaybinaykiya/gmail-organizer.git
   cd gmail-organizer
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Set up Google API credentials:
   - Go to the [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project
   - Enable the Gmail API
   - Create OAuth 2.0 credentials
   - Download the credentials as `credentials.json` and place it in the project root

## Usage

1. Run the application:
   ```
   python app.py
   ```

2. Open your browser and navigate to:
   ```
   http://localhost:5000
   ```

3. Authenticate with your Google account when prompted

## Project Structure

- `app.py`: Main application file with Flask routes and Gmail API integration
- `static/`: Static assets (CSS, JavaScript)
- `templates/`: HTML templates
- `email_cache/`: Cached email data (created at runtime)

## License

MIT

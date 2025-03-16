#!/bin/bash
echo "Setting up Gmail Email Cleaner..."

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

echo "Setup complete. To run the application, use:"
echo "source venv/bin/activate && python app.py"

#!/bin/bash
# Setup script for TeleMind Bot

# Function to display messages
print_message() {
  echo "🤖 $1"
}

# Check if Python is installed
if command -v python3 &>/dev/null; then
  print_message "Python detected ✅"
  PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
  print_message "Python detected ✅"
  PYTHON_CMD="python"
else
  print_message "❌ Python not found. Please install Python 3.9 or higher."
  exit 1
fi

# Create virtual environment
print_message "Creating virtual environment..."
$PYTHON_CMD -m venv venv

# Activate virtual environment
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
  print_message "Activating virtual environment (Windows)..."
  source venv/Scripts/activate
else
  print_message "Activating virtual environment (Unix)..."
  source venv/bin/activate
fi

# Install dependencies
print_message "Installing dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
  print_message "Creating .env file from template..."
  cp .env.sample .env
  print_message "⚠️ Please edit the .env file with your API keys and configuration."
fi

# Create downloads directory
print_message "Creating downloads directory..."
mkdir -p downloads

print_message "Setup complete! 🚀"
print_message "Next steps:"
print_message "1. Edit the .env file with your API keys"
print_message "2. Place your Firebase service account JSON file in the root directory"
print_message "3. Start the bot with: uvicorn main:app --reload"

# PowerShell setup script for TeleMind Bot

# Function to display messages
function Print-Message {
    param([string]$Message)
    Write-Host "🤖 $Message"
}

# Check if Python is installed
if (Get-Command python -ErrorAction SilentlyContinue) {
    Print-Message "Python detected ✅"
    $PYTHON_CMD = "python"
}
elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    Print-Message "Python detected ✅"
    $PYTHON_CMD = "python3"
}
else {
    Print-Message "❌ Python not found. Please install Python 3.9 or higher."
    exit 1
}

# Create virtual environment
Print-Message "Creating virtual environment..."
& $PYTHON_CMD -m venv venv

# Activate virtual environment
Print-Message "Activating virtual environment..."
& .\venv\Scripts\Activate.ps1

# Install dependencies
Print-Message "Installing dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if (!(Test-Path .env)) {
    Print-Message "Creating .env file from template..."
    Copy-Item .env.sample .env
    Print-Message "⚠️ Please edit the .env file with your API keys and configuration."
}

# Create downloads directory
Print-Message "Creating downloads directory..."
New-Item -ItemType Directory -Force -Path .\downloads

Print-Message "Setup complete! 🚀"
Print-Message "Next steps:"
Print-Message "1. Edit the .env file with your API keys"
Print-Message "2. Place your Firebase service account JSON file in the root directory"
Print-Message "3. Start the bot with: uvicorn main:app --reload"

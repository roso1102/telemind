# TeleMind Bot - Clean Project Structure

After cleanup, here are the essential files remaining in your project:

## Core Application Files
- **main.py** - Main bot application with Telegram webhook and AI integration
- **firebase_storage_helper.py** - Enhanced Firebase Storage integration with metadata
- **file_commands.py** - File management commands for the bot
- **test_pymupdf.py** - PDF text extraction utility (supports remote URLs)

## Configuration Files
- **.env** - Environment variables (keep private)
- **.env.sample** - Sample environment file template
- **firebase_service_account.json** - Firebase credentials (keep private)
- **requirements.txt** - Python dependencies

## Deployment Files
- **Dockerfile** - Docker configuration for containerized deployment
- **render.yaml** - Render.com deployment configuration
- **start.sh** - Shell script to start the application
- **setup.ps1** / **setup.sh** - Setup scripts for Windows/Linux

## Documentation
- **readme.md** - Main project documentation
- **DEPLOYMENT_GUIDE.md** - Deployment instructions

## Utility Files
- **check_firebase.py** - Firebase connection testing
- **check_firebase_storage.py** - Firebase Storage testing

## Directories
- **.venv/** - Python virtual environment
- **local_storage/** - Local file storage directory
- **.git/** - Git repository data

## Files Removed
- All Google Drive integration files (drive_*.py, OAuth configs)
- Duplicate/old main files (fixed_main.py, telegram_bot.py, etc.)
- Test files and sample documents
- Unused API integrations (gemini_api.py, scheduler.py)
- Multiple documentation files (consolidated into main readme.md)
- Temporary directories (downloads/, telemind/, __pycache__)

Your project is now clean and contains only the essential files needed for the TeleMind bot to function with Firebase Storage.

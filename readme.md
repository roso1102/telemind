# TeleMind Bot: Advanced Telegram AI Assistant

TeleMind Bot is a powerful Telegram assistant that combines ChatGPT-like intelligence with agent capabilities - all accessible through Telegram. It helps you manage tasks, store notes, process documents, and provide intelligent responses to your questions.

## Features

### Conversational AI with Memory
- Understands natural language (powered by Groq LLM models)
- Remembers tasks, notes, and conversations across sessions
- Can be told to "remember" or "remind me at..." and actually notify you

### Task & Reminder Management
- Create tasks with due dates and times using natural language
- List, update, and mark tasks as complete
- Get notifications for upcoming tasks

### Note & Document Storage
- Save notes, links, and important information
- Store and process PDFs with automatic text extraction
- Save images with OCR text extraction

### File Intelligence
- PDF summarization and content extraction
- Image OCR and text recognition
- Semantic search across documents and notes (in development)

## Setup Instructions

### 1. Prerequisites
- Python 3.9+
- Firebase project (for database & storage)
- Telegram Bot token (via BotFather)
- Groq API key (for LLM access)

### 2. Environment Variables
Set the following environment variables:
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GROQ_API_KEY=your_groq_api_key
FIREBASE_SERVICE_ACCOUNT=your_firebase_service_account_json
```

### 3. Installation
```bash
pip install -r requirements.txt
```

### 4. Running Locally
```bash
uvicorn main:app --reload
```

### 5. Deploying to Render
1. Create a new Web Service on Render
2. Point to your GitHub repo with this code
3. Set the build command: `pip install -r requirements.txt`
4. Set the start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add the environment variables mentioned above

## Troubleshooting

### Bot Not Responding
1. Check webhook status using `check_webhook.py`:
```bash
python check_webhook.py --check
```

2. Set a new webhook if needed:
```bash
python check_webhook.py --set https://your-render-url.onrender.com/webhook
```

### Fixing Syntax Errors
If you encounter syntax errors in the webhook handler:
1. Use the fixed version in `fixed_main.py` 
2. Copy it over to `main.py`:
```bash
cp fixed_main.py main.py
```

### 404 Errors
The bot now has a proper health endpoint at the root path (`/`) that supports both GET and HEAD requests. UptimeRobot can use this to monitor the service.

### Firebase Issues
Make sure your FIREBASE_SERVICE_ACCOUNT environment variable contains the full JSON of your service account credentials.

## Technical Stack

| Feature | Tool |
|---------|------|
| Bot backend | Python + FastAPI |
| AI processing | Groq API |
| Database | Firebase Firestore |
| File Storage | Firebase Storage |
| PDF Processing | PyMuPDF |
| OCR | Tesseract OCR |

## License
MIT License

## Original Requirements
The initial project requirements are preserved in [README_ORIGINAL.md](README_new.md)
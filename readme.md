# TeleMind Bot: Advanced Telegram AI Assistant

TeleMind Bot is a powerful Telegram assistant that combines ChatGPT-like intelligence with agent capabilities - all accessible through Telegram. It helps you manage tasks, store notes, process documents, and provide intelligent responses to your questions.

## Features

### Conversational AI with Memory
- Understands natural language (powered by LLaMA3)
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
- A Telegram bot token (from @BotFather)
- A Groq API key
- Firebase project with Firestore and Storage

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/yourusername/telemind-bot.git
cd telemind-bot

# Setup using script (Unix/Mac)
chmod +x setup.sh
./setup.sh

# OR for Windows
.\setup.ps1

# Edit the .env file with your credentials
```

### 3. Run the Bot
```bash
uvicorn main:app --reload
```

## Technical Stack

| Feature | Tool |
|---------|------|
| Bot backend | Python + FastAPI |
| AI processing | Groq API (LLaMA3) |
| Database | Firebase Firestore |
| Reminders | Firestore timestamps |
| File Storage | Firebase Storage |
| PDF Processing | PyMuPDF |
| OCR | Tesseract OCR |

## Deployment Options

See the [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for detailed instructions on:
- Deploying to Render
- Deploying to Fly.io
- Deploying to Railway
- Managing Firebase in production

## Development Roadmap

- **Vector Search Implementation**: Add embeddings for semantic search
- **Multi-user Support**: Add user authentication and profiles  
- **Dashboard**: Web UI for managing tasks, notes, and files
- **Advanced Document Analysis**: More sophisticated document processing

## Original Requirements
The initial project requirements are preserved in [README_ORIGINAL.md](README_new.md)
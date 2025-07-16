import os
import re
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any

# --- Core Dependencies ---
from fastapi import FastAPI, Request, BackgroundTasks
import httpx
from groq import Groq
from pydantic import BaseModel

# --- Firebase Setup ---
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import storage as firebase_storage

# --- PDF Processing ---
import fitz  # PyMuPDF
from PIL import Image
try:
    import pytesseract  # For OCR
except ImportError:
    print("pytesseract not installed. OCR functionality will be limited.")

# --- Logging helper ---
def log(msg, *args, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {timestamp} | {msg}", *args, flush=True)

# --- Environment Variables ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not GROQ_API_KEY:
    log("GROQ_API_KEY is not set!", level="ERROR")
if not TELEGRAM_BOT_TOKEN:
    log("TELEGRAM_BOT_TOKEN is not set!", level="ERROR")

# --- Initialize clients ---
# Groq client for LLM
groq_client = Groq(api_key=GROQ_API_KEY)
API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# --- Firebase Initialization ---
try:
    # Check if Firebase service account is provided as env variable
    firebase_service_account = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    if firebase_service_account:
        # Create temporary file with the service account JSON
        import tempfile
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, 'w') as tmp:
            tmp.write(firebase_service_account)
        
        cred = credentials.Certificate(path)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'telemindbot-f271b.appspot.com'  # Your bucket name
        })
        
        # Clean up the temporary file
        os.remove(path)
    else:
        # If running on local development with file
        try:
            cred = credentials.Certificate("firebase_service_account.json")
            firebase_admin.initialize_app(cred, {
                'storageBucket': 'telemindbot-f271b.appspot.com'  # Your bucket name
            })
        except Exception as e:
            log(f"Local Firebase initialization error: {e}", level="ERROR")
            # Last resort - try app default credentials
            firebase_admin.initialize_app()
except Exception as e:
    log(f"Firebase initialization error: {e}", level="ERROR")
    try:
        firebase_admin.initialize_app()
    except ValueError:
        log("Firebase app already initialized", level="WARNING")

# Initialize Firestore
db = firestore.client()
bucket = firebase_storage.bucket()

# --- FastAPI app ---
app = FastAPI()

# --- Data Models ---
class Message(BaseModel):
    role: str
    content: str
    timestamp: Optional[float] = None
    
    def dict(self, *args, **kwargs):
        """Override dict method to handle Firestore timestamps"""
        result = super().dict(*args, **kwargs)
        # Ensure timestamp is a simple value, not a Firestore Sentinel
        if "timestamp" in result and isinstance(result["timestamp"], object) and hasattr(result["timestamp"], "__class__") and "Sentinel" in str(result["timestamp"].__class__):
            result["timestamp"] = time.time()
        return result

class UserSession:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.messages: List[Message] = []
        self.last_interaction: float = time.time()
        self.context_window = 10  # Store last 10 messages

# Active user sessions (memory)
user_sessions: Dict[str, UserSession] = {}

# --- API endpoints ---
@app.get("/", response_model=dict)
@app.head("/", response_model=dict)
async def root():
    """Root endpoint"""
    return {"status": "ok", "service": "TeleMind Bot", "timestamp": time.time()}

@app.get("/health", response_model=dict)
@app.head("/health", response_model=dict)
async def health_check():
    """Health check endpoint specifically for monitoring services"""
    return {"status": "ok", "service": "TeleMind Bot", "timestamp": time.time()}

@app.get("/debug", response_model=dict)
async def debug_info():
    """Debug endpoint"""
    env_vars = {
        "GROQ_API_KEY": bool(GROQ_API_KEY),  # Just show if it exists, not the actual value
        "TELEGRAM_BOT_TOKEN": bool(TELEGRAM_BOT_TOKEN),
        "FIREBASE_SERVICE_ACCOUNT": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT"))
    }
    return {
        "env": env_vars,
        "timestamp": time.time(),
        "sessions": len(user_sessions)
    }

# --- Webhook handler ---
@app.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming Telegram webhook"""
    chat_id = None
    user_id = None
    
    try:
        # Parse the incoming webhook data
        data = await request.json()
        log(f"Received webhook: {data}")
        
        if "message" not in data:
            log("No message in webhook data", level="WARNING")
            return {"ok": True}
        
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = str(message["from"]["id"])
        
        # Process different message types
        if "text" in message:
            # Handle text messages
            text = message["text"]
            log(f"Handling message: {text} from user {user_id}")
            
            # Process commands
            if text.startswith("/"):
                cmd = text.split()[0].lower()
                
                if cmd == "/start":
                    await send_message(chat_id, "👋 Hello! I'm your personal assistant. I can help you with tasks, notes, and files. How can I assist you today?")
                    return {"ok": True}
                    
                elif cmd == "/help":
                    help_text = """
I can help you with:

*Task Management*
- "Remind me to pay rent on Friday"
- "Add task: buy groceries tomorrow"
- "Show my tasks"

*Notes & Information*
- "Remember my wifi password is 12345678"
- "Save this note: [your note]"
- "What was my wifi password?"

*File Management*
- Send me any PDF, image, or document
- "What did that PDF about marketing say?"
- "Find information about pancreatic cells"

Just chat naturally with me!
"""
                    await send_message(chat_id, help_text)
                    return {"ok": True}
                    
                elif cmd == "/tasks":
                    # Get user tasks
                    user_data = await get_user_data(user_id)
                    tasks = user_data.get("tasks", [])
                    
                    if not tasks:
                        await send_message(chat_id, "📭 You don't have any tasks yet.")
                    else:
                        reply = "📋 *Your Tasks*:\n\n"
                        for i, task in enumerate(tasks, 1):
                            status = "✅" if task.get("completed") else "⏳"
                            due_str = ""
                            if task.get("due_date"):
                                due_str = f" (Due: {task['due_date']}"
                                if task.get("due_time"):
                                    due_str += f" at {task['due_time']}"
                                due_str += ")"
                                
                            reply += f"{i}. {status} {task['task']}{due_str}\n"
                        
                        await send_message(chat_id, reply)
                    return {"ok": True}
                    
                elif cmd == "/notes":
                    # Get user notes
                    user_data = await get_user_data(user_id)
                    notes = user_data.get("notes", [])
                    
                    if not notes:
                        await send_message(chat_id, "📭 You don't have any notes yet.")
                    else:
                        reply = "📝 *Your Notes*:\n\n"
                        for i, note in enumerate(notes, 1):
                            created = datetime.fromtimestamp(note.get("timestamp", 0))
                            date_str = created.strftime("%Y-%m-%d")
                            reply += f"{i}. {note['content']} _{date_str}_\n\n"
                        
                        await send_message(chat_id, reply)
                    return {"ok": True}
                    
                elif cmd == "/files":
                    # Get user files
                    user_data = await get_user_data(user_id)
                    files = user_data.get("files", [])
                    
                    if not files:
                        await send_message(chat_id, "📭 You don't have any files yet.")
                    else:
                        reply = "🗂 *Your Files*:\n\n"
                        for i, file in enumerate(files, 1):
                            file_type_emoji = "📄" if file.get("type") == "documents" else "🖼" if file.get("type") == "images" else "📁"
                            reply += f"{i}. {file_type_emoji} [{file['name']}]({file['url']})\n"
                        
                        await send_message(chat_id, reply)
                    return {"ok": True}
            
            # Process intent for non-command messages
            intent_data = await analyze_intent(text)
            intent = intent_data.get("intent", "general_chat")
            
            # Handle specific intents
            if intent == "task_create":
                # Extract task details
                task_info = await extract_task_info(text)
                
                if task_info.get("is_task") is False:
                    # Not really a task, fall back to general conversation
                    pass
                else:
                    # Create task in database
                    task_data = {
                        "task": task_info.get("task"),
                        "due_date": task_info.get("due_date"),
                        "due_time": task_info.get("due_time"),
                        "priority": task_info.get("priority", "medium"),
                        "completed": False,
                        "created_at": firestore.SERVER_TIMESTAMP
                    }
                    
                    await add_to_user_array(user_id, "tasks", task_data)
                    
                    # Craft response
                    due_str = ""
                    if task_info.get("due_date"):
                        due_str = f" for {task_info['due_date']}"
                        if task_info.get("due_time"):
                            due_str += f" at {task_info['due_time']}"
                    
                    response = f"✅ Task added: {task_info.get('task')}{due_str}"
                    await send_message(chat_id, response)
                    return {"ok": True}
            
            elif intent == "note_create":
                # Create note in database
                note_data = {
                    "content": text,
                    "timestamp": time.time(),
                }
                
                await add_to_user_array(user_id, "notes", note_data)
                await send_message(chat_id, "📝 Note saved!")
                return {"ok": True}
            
            # Default: process as conversation
            response = await process_conversation(user_id, text)
            await send_message(chat_id, response)
            
        elif "document" in message:
            # Handle document/file uploads
            doc = message["document"]
            file_id = doc["file_id"]
            file_name = doc["file_name"]
            
            # Get file info and download
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{API_URL}/getFile?file_id={file_id}")
                file_path = res.json()["result"]["file_path"]
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                
                # Download file
                local_path = f"downloads/{file_id}_{file_name}"
                os.makedirs("downloads", exist_ok=True)
                
                file_data = await client.get(file_url)
                with open(local_path, "wb") as f:
                    f.write(file_data.content)
            
            # Process file based on type
            if file_name.lower().endswith(('.pdf')):
                # Process PDF in background
                await send_message(chat_id, f"📄 Processing document: {file_name}...")
                response = await process_document(user_id, local_path, file_name)
                await send_message(chat_id, response)
            elif file_name.lower().endswith(('.jpg', '.jpeg', '.png')):
                # Process image
                await send_message(chat_id, f"🖼 Processing image: {file_name}...")
                file_url = await store_file(user_id, local_path, file_name, "images")
                
                # Try OCR
                text = await extract_text_from_image(local_path)
                if text:
                    # Store text content for search
                    img_data = {
                        "name": file_name,
                        "text": text,
                        "url": file_url,
                        "created_at": firestore.SERVER_TIMESTAMP
                    }
                    
                    # Add to user's documents collection
                    loop = asyncio.get_event_loop()
                    doc_ref = db.collection("users").document(str(user_id)).collection("document_contents")
                    await loop.run_in_executor(None, lambda: doc_ref.add(img_data))
                    
                    await send_message(chat_id, f"🖼 Image saved: {file_name}\n\nText extracted: {text[:100]}...")
                else:
                    await send_message(chat_id, f"🖼 Image saved: {file_name}")
            else:
                # Generic file
                file_url = await store_file(user_id, local_path, file_name, "other_files")
                await send_message(chat_id, f"📁 File saved: {file_name}")
            
            # Clean up
            try:
                os.remove(local_path)
            except Exception as e:
                log(f"Error removing temp file: {e}", level="WARNING")
                
        elif "photo" in message:
            # Handle photos
            photo = message["photo"][-1]  # Last is the largest
            file_id = photo["file_id"]
            
            # Generate a filename
            file_name = f"photo_{int(time.time())}.jpg"
            
            # Get file info and download
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{API_URL}/getFile?file_id={file_id}")
                file_path = res.json()["result"]["file_path"]
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                
                # Download file
                local_path = f"downloads/{file_id}_{file_name}"
                os.makedirs("downloads", exist_ok=True)
                
                file_data = await client.get(file_url)
                with open(local_path, "wb") as f:
                    f.write(file_data.content)
            
            # Process image
            await send_message(chat_id, "🖼 Processing image...")
            file_url = await store_file(user_id, local_path, file_name, "images")
            
            # Try OCR
            text = await extract_text_from_image(local_path)
            if text:
                # Store text content for search
                img_data = {
                    "name": file_name,
                    "text": text,
                    "url": file_url,
                    "created_at": firestore.SERVER_TIMESTAMP
                }
                
                # Add to user's documents collection
                loop = asyncio.get_event_loop()
                doc_ref = db.collection("users").document(str(user_id)).collection("document_contents")
                await loop.run_in_executor(None, lambda: doc_ref.add(img_data))
                
                await send_message(chat_id, f"🖼 Image saved!\n\nText extracted: {text[:100]}...")
            else:
                await send_message(chat_id, "🖼 Image saved!")
                
            # Clean up
            try:
                os.remove(local_path)
            except Exception as e:
                log(f"Error removing temp file: {e}", level="WARNING")
                
    except Exception as e:
        log(f"Unhandled error in webhook handler: {e}", level="ERROR")
        # Try to send a message to the user if possible
        try:
            if chat_id:
                await send_message(chat_id, "Sorry, I encountered an unexpected error. Please try again.")
        except Exception as inner_e:
            log(f"Error sending error message: {inner_e}", level="ERROR")
    
    # Always return success to Telegram
    return {"ok": True}

@app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment variables"""
    # Only return non-sensitive info
    return {
        "WEBHOOK_URL": os.getenv("WEBHOOK_URL"),
        "WEBHOOK_URL_configured": bool(os.getenv("WEBHOOK_URL")),
        "TELEGRAM_BOT_TOKEN_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "GROQ_API_KEY_configured": bool(os.getenv("GROQ_API_KEY")),
        "FIREBASE_SERVICE_ACCOUNT_configured": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT"))
    }

# --- Main execution ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

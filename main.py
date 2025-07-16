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
    
# --- OCR Helper ---
async def extract_text_from_image(image_path: str) -> str:
    """Extract text from an image using OCR"""
    try:
        # Check if pytesseract is available
        if 'pytesseract' not in globals():
            log("OCR skipped - pytesseract not installed", level="WARNING")
            return ""
            
        # Process with OCR
        loop = asyncio.get_event_loop()
        
        # Check if a custom Tesseract path is specified
        tesseract_cmd = os.getenv("TESSERACT_PATH")
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            
        # Process image with pytesseract
        img = Image.open(image_path)
        result = await loop.run_in_executor(None, lambda: pytesseract.image_to_string(img))
        return result
    except Exception as e:
        log(f"Error extracting text from image: {e}", level="ERROR")
        return ""

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

# --- Message processing helpers ---
async def send_message(chat_id: int, text: str):
    """Send message to user via Telegram"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{API_URL}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            })
            
            # Check if the response was successful
            response_data = response.json()
            if not response_data.get("ok"):
                log(f"Telegram API error: {response_data}", level="ERROR")
    except Exception as e:
        log(f"Error sending message to Telegram: {e}", level="ERROR")

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

# --- Firebase helpers ---
async def get_user_data(user_id: str) -> dict:
    """Get user data from Firestore"""
    loop = asyncio.get_event_loop()
    doc_ref = db.collection("users").document(str(user_id))
    doc = await loop.run_in_executor(None, doc_ref.get)
    if not doc.exists:
        # Initialize user data
        default_data = {
            "notes": [],
            "tasks": [],
            "files": [],
            "conversation": [],
            "created_at": time.time()  # Use time.time() instead of Firestore.SERVER_TIMESTAMP
        }
        await loop.run_in_executor(None, lambda: doc_ref.set(default_data))
        return default_data
    return doc.to_dict()

async def update_user_data(user_id: str, data: dict, merge: bool = True):
    """Update user data in Firestore"""
    loop = asyncio.get_event_loop()
    doc_ref = db.collection("users").document(str(user_id))
    await loop.run_in_executor(None, lambda: doc_ref.set(data, merge=merge))

async def add_to_user_array(user_id: str, field: str, value: Any):
    """Add an item to a user's array field"""
    # Convert any SERVER_TIMESTAMP values to actual timestamps before storing
    if isinstance(value, dict):
        for k, v in list(value.items()):
            if isinstance(v, object) and hasattr(v, "__class__") and "Sentinel" in str(v.__class__):
                value[k] = time.time()
    
    loop = asyncio.get_event_loop()
    doc_ref = db.collection("users").document(str(user_id))
    await loop.run_in_executor(None, 
                              lambda: doc_ref.update({field: firestore.ArrayUnion([value])}))

async def store_file(user_id: str, file_path: str, file_name: str, file_type: str) -> str:
    """Store file in Firebase Storage and return URL"""
    # Upload to Firebase Storage
    destination_path = f"users/{user_id}/{file_type}/{file_name}"
    blob = bucket.blob(destination_path)
    
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: blob.upload_from_filename(file_path))
    
    # Make publicly accessible and get URL
    await loop.run_in_executor(None, lambda: blob.make_public())
    url = blob.public_url
    
    # Store metadata in Firestore
    file_data = {
        "name": file_name,
        "type": file_type,
        "url": url,
        "path": destination_path,
        "uploaded_at": time.time()  # Use time.time() instead of Firestore.SERVER_TIMESTAMP
    }
    await add_to_user_array(user_id, "files", file_data)
    
    return url

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
                        "created_at": time.time()  # Use time.time() instead of Firestore.SERVER_TIMESTAMP
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
                        "created_at": time.time()  # Use time.time() instead of Firestore.SERVER_TIMESTAMP
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
                    "created_at": time.time()  # Use time.time() instead of Firestore.SERVER_TIMESTAMP
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

# --- AI Processing Functions ---
async def process_conversation(user_id: str, new_message: str) -> str:
    """Process user message through LLM and return response"""
    # Get user session or create new one
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
        
    session = user_sessions[user_id]
    session.last_interaction = time.time()
    
    # Add user message to history
    user_msg = Message(role="user", content=new_message, timestamp=time.time())
    session.messages.append(user_msg)
    
    # Keep only the last N messages for context window
    if len(session.messages) > session.context_window:
        session.messages = session.messages[-session.context_window:]
    
    # Format conversation for the LLM
    messages = [{"role": msg.role, "content": msg.content} for msg in session.messages]
    
    # Add system prompt
    system_prompt = """You are TeleMind, a helpful personal assistant on Telegram.
You help users manage tasks, take notes, and handle files.
Be friendly and concise in your responses.
Your goal is to help users organize their lives and provide useful information."""
    
    messages.insert(0, {"role": "system", "content": system_prompt})
    
    try:
        # Call Groq API
        response = await asyncio.to_thread(
            groq_client.chat.completions.create,
            model="llama3-8b-8192",
            messages=messages,
            temperature=0.7,
            max_tokens=800
        )
        
        # Extract response text
        assistant_response = response.choices[0].message.content
        
        # Save assistant response to history
        assistant_msg = Message(role="assistant", content=assistant_response, timestamp=time.time())
        session.messages.append(assistant_msg)
        
        return assistant_response
    except Exception as e:
        log(f"Error calling Groq API: {e}", level="ERROR")
        return "I apologize, but I encountered an issue processing your request. Please try again."

async def analyze_intent(text: str) -> dict:
    """Analyze the user's message intent"""
    # Simple rule-based intent detection
    text_lower = text.lower()
    
    # Check for task creation intent
    if any(phrase in text_lower for phrase in ["remind me to", "add task", "create task", "remember to", "don't forget to"]):
        return {"intent": "task_create"}
    
    # Check for note creation intent
    if any(phrase in text_lower for phrase in ["save note", "save this", "take note", "note this", "remember this", "remember that"]):
        return {"intent": "note_create"}
    
    # Default to general conversation
    return {"intent": "general_chat"}

async def extract_task_info(text: str) -> dict:
    """Extract task details from user message"""
    # Simple implementation for now
    # In a production system, this would use NLP to extract dates, times, etc.
    
    text_lower = text.lower()
    
    # Check if it's really a task
    if not any(phrase in text_lower for phrase in ["remind me to", "add task", "create task", "remember to", "don't forget to"]):
        return {"is_task": False}
    
    # Extract potential date patterns
    date_match = re.search(r'(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}/\d{1,2}|\d{1,2}-\d{1,2})', text_lower)
    date = date_match.group(1) if date_match else None
    
    # Extract potential time patterns
    time_match = re.search(r'(\d{1,2}:\d{2}|\d{1,2} (am|pm))', text_lower)
    time = time_match.group(1) if time_match else None
    
    # Clean up the task description
    task = text
    for prefix in ["remind me to", "add task:", "add task", "create task:", "create task", "remember to", "don't forget to"]:
        if prefix in text_lower:
            task = text[text_lower.find(prefix) + len(prefix):].strip()
            break
    
    return {
        "is_task": True,
        "task": task,
        "due_date": date,
        "due_time": time,
        "priority": "medium"  # Default priority
    }

async def process_document(user_id: str, file_path: str, file_name: str) -> str:
    """Process a PDF document and extract text"""
    try:
        # Extract text from PDF
        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
        
        # Store the extracted text in Firestore
        if text:
            # Store text content for search
            pdf_data = {
                "name": file_name,
                "text": text,
                "created_at": time.time()  # Use time.time() instead of Firestore.SERVER_TIMESTAMP
            }
            
            # Store file in Firebase Storage
            file_url = await store_file(user_id, file_path, file_name, "documents")
            pdf_data["url"] = file_url
            
            # Add to user's documents collection
            loop = asyncio.get_event_loop()
            doc_ref = db.collection("users").document(str(user_id)).collection("document_contents")
            await loop.run_in_executor(None, lambda: doc_ref.add(pdf_data))
            
            return f"📄 Document saved: {file_name}\n\nExtracted {len(text)} characters of text."
        else:
            return f"📄 Document saved: {file_name}\n\nNo text could be extracted."
    except Exception as e:
        log(f"Error processing document: {e}", level="ERROR")
        return f"📄 Document saved, but there was an error processing it: {str(e)[:100]}"

# --- Main execution ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

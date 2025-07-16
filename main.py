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

# --- Vector Search (when we implement it) ---
# from langchain_community.vectorstores import FAISS
# from langchain_community.embeddings import HuggingFaceEmbeddings

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
    # If running on local development
    cred = credentials.Certificate("firebase_service_account.json")
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'telemind-bot.appspot.com'  # Replace with your bucket
    })
except Exception as e:
    log(f"Firebase initialization error: {e}", level="ERROR")
    # Fallback to environment variables if in production
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
            "created_at": firestore.SERVER_TIMESTAMP
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
        "uploaded_at": firestore.SERVER_TIMESTAMP
    }
    await add_to_user_array(user_id, "files", file_data)
    
    return url

# --- Message processing ---
async def send_message(chat_id: int, text: str):
    """Send message to user via Telegram"""
    async with httpx.AsyncClient() as client:
        await client.post(f"{API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        })

async def process_conversation(user_id: str, new_message: str) -> str:
    """Process user message through Groq and return response"""
    # Get user session or create new one
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
        # Load conversation history from Firestore
        user_data = await get_user_data(user_id)
        if "conversation" in user_data:
            for msg in user_data["conversation"][-5:]:  # Last 5 messages
                user_sessions[user_id].messages.append(
                    Message(**msg)
                )
    
    session = user_sessions[user_id]
    
    # Add user message to session
    user_msg = Message(role="user", content=new_message, timestamp=time.time())
    session.messages.append(user_msg)
    
    # Prepare conversation for Groq
    messages = [{"role": msg.role, "content": msg.content} 
               for msg in session.messages[-session.context_window:]]
    
    # Add system message at the beginning
    system_message = {
        "role": "system", 
        "content": """You are an intelligent assistant in a Telegram bot. 
You help users manage tasks, notes, and files. You can understand requests to:
1. Remember information or create notes
2. Set reminders and tasks with dates and times
3. Summarize or extract information from files
4. Answer questions using your knowledge

Be concise, helpful, and friendly in your responses.
"""
    }
    messages.insert(0, system_message)
    
    try:
        # Call Groq API
        response = groq_client.chat.completions.create(
            model="llama3-8b-8192",  # Using LLaMA 3 8B model
            messages=messages,
            temperature=0.7,
            max_tokens=800
        )
        
        assistant_response = response.choices[0].message.content
        
        # Save assistant response to session
        assistant_msg = Message(role="assistant", content=assistant_response, timestamp=time.time())
        session.messages.append(assistant_msg)
        
        # Update last interaction time
        session.last_interaction = time.time()
        
        # Store the last few messages in Firestore for persistence
        conversation_to_store = [msg.dict() for msg in session.messages[-5:]]
        await update_user_data(user_id, {"conversation": conversation_to_store})
        
        return assistant_response
        
    except Exception as e:
        log(f"Error calling Groq API: {e}", level="ERROR")
        return "I'm having trouble thinking right now. Please try again in a moment."

async def extract_task_info(text: str) -> dict:
    """Extract task information using LLM"""
    prompt = f"""
Extract task or reminder information from this text. 
If there's a task or reminder, provide JSON with these fields:
- task: The task description
- due_date: ISO format date (YYYY-MM-DD) or null if not specified
- due_time: 24-hour format time (HH:MM) or null if not specified
- priority: "high", "medium", "low", or null if not specified

If there's no task, return {{"is_task": false}}

Text: "{text}"
    """
    
    try:
        response = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        
        result_text = response.choices[0].message.content
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not json_match:
            return {"is_task": False}
            
        json_str = json_match.group(0)
        return json.loads(json_str)
        
    except Exception as e:
        log(f"Error extracting task info: {e}", level="ERROR")
        return {"is_task": False}

async def analyze_intent(text: str) -> dict:
    """Analyze user intent using LLM"""
    prompt = f"""
Analyze the user's intent in this message. Categorize as one of:
- task_create: Create a task or reminder
- task_list: Show or list tasks
- task_update: Update or complete a task
- note_create: Create or save a note
- note_retrieve: Retrieve or search notes
- file_query: Query about file contents
- general_chat: General conversation

Return JSON with "intent" and "entities" fields.

Message: "{text}"
    """
    
    try:
        response = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        
        result_text = response.choices[0].message.content
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not json_match:
            return {"intent": "general_chat", "entities": {}}
            
        json_str = json_match.group(0)
        return json.loads(json_str)
        
    except Exception as e:
        log(f"Error analyzing intent: {e}", level="ERROR")
        return {"intent": "general_chat", "entities": {}}

# --- File processing ---
async def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF file"""
    try:
        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
        return text
    except Exception as e:
        log(f"Error extracting text from PDF: {e}", level="ERROR")
        return ""

async def extract_text_from_image(file_path: str) -> str:
    """Extract text from image using OCR"""
    try:
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img)
        return text
    except Exception as e:
        log(f"Error extracting text from image: {e}", level="ERROR")
        return ""

async def process_document(user_id: str, file_path: str, file_name: str) -> str:
    """Process a document file (PDF) and store info"""
    # Store file
    file_url = await store_file(user_id, file_path, file_name, "documents")
    
    # Extract text
    text = await extract_text_from_pdf(file_path)
    
    if text:
        # Store text content for search
        doc_data = {
            "name": file_name,
            "text": text,
            "url": file_url,
            "created_at": firestore.SERVER_TIMESTAMP
        }
        
        # Add to user's documents collection
        loop = asyncio.get_event_loop()
        doc_ref = db.collection("users").document(str(user_id)).collection("document_contents")
        await loop.run_in_executor(None, lambda: doc_ref.add(doc_data))
        
        # Generate summary if text is long enough
        if len(text) > 100:
            summary_prompt = f"Summarize the following document in a few bullet points:\n\n{text[:5000]}"
            try:
                response = groq_client.chat.completions.create(
                    model="llama3-8b-8192",
                    messages=[{"role": "user", "content": summary_prompt}],
                    temperature=0.5
                )
                summary = response.choices[0].message.content
                
                # Update document with summary
                await loop.run_in_executor(None, lambda: doc_ref.update({"summary": summary}))
                
                return f"📄 Document saved: {file_name}\n\n📝 Summary:\n{summary}"
            except Exception as e:
                log(f"Error generating summary: {e}", level="ERROR")
        
    return f"📄 Document saved: {file_name}"

# --- Webhook handler ---
@app.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming Telegram webhook"""
    data = await request.json()
    log(f"Received webhook: {data}")
    
    if "message" not in data:
        return {"ok": True}
    
    message = data["message"]
    chat_id = message["chat"]["id"]
    user_id = str(message["from"]["id"])
    
    # Handle text messages
    if "text" in message:
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
    
    # Handle document/file uploads
    elif "document" in message:
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
        except:
            pass
            
    # Handle photos
    elif "photo" in message:
        # Get the largest photo
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
        except:
            pass
    
    return {"ok": True}

@app.get("/")
async def root():
    """Root endpoint for checking if service is running"""
    return {"status": "ok", "message": "TeleMind Bot is running!"}

# --- Register webhook with Telegram ---
@app.on_event("startup")
async def startup_event():
    """Set webhook on startup"""
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        try:
            async with httpx.AsyncClient() as client:
                # Delete existing webhook first
                await client.get(f"{API_URL}/deleteWebhook")
                # Set new webhook
                response = await client.get(
                    f"{API_URL}/setWebhook",
                    params={"url": f"{WEBHOOK_URL}/webhook"}
                )
                result = response.json()
                if result.get("ok"):
                    log(f"Webhook set to {WEBHOOK_URL}/webhook")
                else:
                    log(f"Failed to set webhook: {result}", level="ERROR")
        except Exception as e:
            log(f"Error setting webhook: {e}", level="ERROR")
    else:
        log("WEBHOOK_URL not set, webhook not configured", level="WARNING")

# --- Cleanup task to periodically save sessions to Firestore ---
@app.on_event("startup")
async def setup_periodic_tasks():
    """Set up periodic tasks for maintenance"""
    async def cleanup_sessions():
        while True:
            try:
                # Wait for next cleanup interval
                await asyncio.sleep(600)  # Every 10 minutes
                
                now = time.time()
                users_to_remove = []
                
                for user_id, session in user_sessions.items():
                    # If session is older than 30 minutes, save to Firestore and remove
                    if now - session.last_interaction > 1800:  # 30 minutes
                        # Save conversation to Firestore before removing
                        conversation_to_store = [msg.dict() for msg in session.messages[-5:]]
                        await update_user_data(user_id, {"conversation": conversation_to_store})
                        users_to_remove.append(user_id)
                
                # Remove stale sessions
                for user_id in users_to_remove:
                    del user_sessions[user_id]
                    
                log(f"Cleaned up {len(users_to_remove)} stale sessions")
                    
            except Exception as e:
                log(f"Error in cleanup task: {e}", level="ERROR")
    
    # Start the background task
    asyncio.create_task(cleanup_sessions())

# --- Main execution ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

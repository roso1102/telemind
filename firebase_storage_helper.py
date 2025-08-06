"""
Firebase Storage Helper Module
Optimized for working with Firebase Storage on Render.com's ephemeral filesystem
"""

import os
import io
import time
import json
import requests
import tempfile
import firebase_admin
from firebase_admin import credentials, storage, firestore
from urllib.parse import urlparse, quote
from datetime import datetime
import hashlib
import PyPDF2

# Initialize Firebase if not already initialized
def get_firebase_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        # Try to initialize
        try:
            # Try with service account file
            if os.path.exists("firebase_service_account.json"):
                cred = credentials.Certificate("firebase_service_account.json")
                return firebase_admin.initialize_app(cred, {
                    'storageBucket': os.environ.get("FIREBASE_STORAGE_BUCKET", "telemind-assistant.appspot.com")
                })
            # Try with environment variable
            elif os.environ.get("FIREBASE_SERVICE_ACCOUNT"):
                import tempfile
                fd, path = tempfile.mkstemp()
                with os.fdopen(fd, 'w') as tmp:
                    tmp.write(os.environ.get("FIREBASE_SERVICE_ACCOUNT"))
                cred = credentials.Certificate(path)
                app = firebase_admin.initialize_app(cred, {
                    'storageBucket': os.environ.get("FIREBASE_STORAGE_BUCKET", "telemind-assistant.appspot.com")
                })
                # Clean up
                os.unlink(path)
                return app
            else:
                # Last resort - try default credentials
                return firebase_admin.initialize_app(options={
                    'storageBucket': os.environ.get("FIREBASE_STORAGE_BUCKET", "telemind-assistant.appspot.com")
                })
        except Exception as e:
            print(f"Firebase initialization error: {e}")
            return None

def get_bucket():
    """Get the Firebase storage bucket"""
    app = get_firebase_app()
    if not app:
        return None
    return storage.bucket()

def get_db():
    """Get the Firestore database"""
    get_firebase_app()  # Ensure Firebase is initialized
    return firestore.client()

def upload_file(user_id, file_path, file_name, file_type, extract_metadata=True):
    """
    Upload a file to Firebase Storage with enhanced metadata
    
    Args:
        user_id: The ID of the user who owns the file
        file_path: Local path to the file
        file_name: Name to use for the file in storage
        file_type: Type of file (pdf, image, etc.)
        extract_metadata: Whether to extract and store additional metadata
    
    Returns:
        Dictionary with file info including URL and metadata
    """
    try:
        # Get bucket
        bucket = get_bucket()
        if not bucket:
            return {"success": False, "error": "Firebase Storage not initialized"}
            
        # Define storage path
        destination_path = f"users/{user_id}/{file_type}/{file_name}"
        blob = bucket.blob(destination_path)
        
        # Upload file
        blob.upload_from_filename(file_path)
        
        # Make publicly accessible
        blob.make_public()
        url = blob.public_url
        
        # Extract metadata based on file type
        metadata = {}
        content_preview = ""
        
        if extract_metadata:
            # Extract text content preview and metadata
            if file_type == 'pdf':
                metadata = extract_pdf_metadata(file_path)
                content_preview = extract_text_preview(file_path, max_chars=500)
            elif file_type in ['jpg', 'jpeg', 'png']:
                metadata = {"format": file_type}
                # You could add image metadata extraction here
        
        # Create a file hash for reference
        file_hash = create_file_hash(file_path)
        
        # Store enhanced metadata in Firestore
        file_data = {
            "name": file_name,
            "type": file_type,
            "url": url,
            "path": destination_path,
            "storage_type": "firebase",
            "uploaded_at": time.time(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "metadata": metadata,
            "content_preview": content_preview,
            "file_hash": file_hash
        }
        
        # Update Firestore
        db = get_db()
        if db:
            db.collection('users').document(user_id).update({
                'files': firestore.ArrayUnion([file_data])
            })
        
        return {
            "success": True, 
            "url": url, 
            "path": destination_path,
            "metadata": metadata,
            "content_preview": content_preview
        }
        
    except Exception as e:
        print(f"Error uploading file to Firebase: {e}")
        return {"success": False, "error": str(e)}

def download_file(url, local_path=None):
    """
    Download a file from Firebase Storage or any URL
    
    Args:
        url: Public URL of the file
        local_path: Path to save the file locally (if None, uses a temp file)
    
    Returns:
        Path to the downloaded file (temporary file if local_path is None)
    """
    try:
        # If URL is not provided or invalid
        if not url or not url.startswith("http"):
            return None
            
        # Download the file
        response = requests.get(url, stream=True)
        if response.status_code != 200:
            print(f"Error downloading file: HTTP {response.status_code}")
            return None
            
        # If no local path specified, create a temporary file
        temp_file = None
        if not local_path:
            # Get filename from URL
            filename = os.path.basename(urlparse(url).path)
            if not filename:
                # Use content disposition if available
                if 'Content-Disposition' in response.headers:
                    import re
                    filename_match = re.findall('filename="(.+)"', response.headers['Content-Disposition'])
                    if filename_match:
                        filename = filename_match[0]
                    else:
                        filename = "downloaded_file"
            
            # Create temp file with a meaningful name
            suffix = f"_{filename}" if filename else ""
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            local_path = temp_file.name
            
        # Save the content
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        return local_path
        
    except Exception as e:
        print(f"Error downloading file: {e}")
        return None

def extract_pdf_metadata(pdf_path):
    """Extract metadata from a PDF file"""
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            info = reader.metadata
            
            if info:
                # Convert to regular dict with string values
                metadata = {
                    "title": info.get("/Title", ""),
                    "author": info.get("/Author", ""),
                    "subject": info.get("/Subject", ""),
                    "creator": info.get("/Creator", ""),
                    "producer": info.get("/Producer", ""),
                    "pages": len(reader.pages)
                }
                return metadata
            else:
                return {"pages": len(reader.pages)}
    except Exception as e:
        print(f"Error extracting PDF metadata: {e}")
        return {}

def extract_text_preview(pdf_path, max_chars=500):
    """Extract a preview of the text from a PDF file"""
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                if len(text) >= max_chars:
                    break
                text += page.extract_text() or ""
            
            # Limit to max_chars
            if len(text) > max_chars:
                text = text[:max_chars] + "..."
                
            return text
    except Exception as e:
        print(f"Error extracting PDF text preview: {e}")
        return ""

def create_file_hash(file_path):
    """Create a hash of a file for identification"""
    try:
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    except Exception as e:
        print(f"Error creating file hash: {e}")
        return ""

def get_user_files(user_id, file_type=None):
    """
    Get all files for a user, optionally filtered by type
    
    Args:
        user_id: The user ID
        file_type: Optional filter for file type (pdf, image, etc.)
        
    Returns:
        List of file data dictionaries
    """
    try:
        db = get_db()
        if not db:
            return []
            
        # Get user document
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            return []
            
        user_data = user_doc.to_dict()
        all_files = user_data.get('files', [])
        
        # Filter by type if specified
        if file_type:
            return [f for f in all_files if f.get('type') == file_type]
        else:
            return all_files
            
    except Exception as e:
        print(f"Error getting user files: {e}")
        return []

def process_pdf(user_id, file_url=None, file_path=None, max_chars=10000):
    """
    Process a PDF file to extract text and metadata
    Works with either a remote URL or local path
    
    Args:
        user_id: The user ID
        file_url: URL to the PDF file
        file_path: Local path to the PDF file
        max_chars: Maximum characters to extract
        
    Returns:
        Dictionary with extracted text and metadata
    """
    try:
        # We need either a URL or a local path
        if not file_url and not file_path:
            return {"success": False, "error": "No file specified"}
            
        # If we have a URL but no local path, download it
        temp_file = None
        if file_url and not file_path:
            file_path = download_file(file_url)
            if not file_path:
                return {"success": False, "error": "Failed to download file"}
            temp_file = file_path
            
        # Import here to avoid circular imports
        from test_pymupdf import extract_text_from_pdf
        
        # Extract text
        extracted_text = extract_text_from_pdf(
            file_path, 
            max_chars=max_chars
        )
        
        # Extract metadata
        metadata = extract_pdf_metadata(file_path)
        
        # Clean up temp file if needed
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except:
                pass
                
        return {
            "success": True,
            "text": extracted_text,
            "metadata": metadata
        }
        
    except Exception as e:
        print(f"Error processing PDF: {e}")
        return {"success": False, "error": str(e)}

def find_files_by_content(user_id, query, limit=5):
    """
    Find files that contain the given query text in their content preview
    
    Args:
        user_id: The user ID
        query: The text to search for
        limit: Maximum number of results to return
        
    Returns:
        List of matching file data dictionaries
    """
    files = get_user_files(user_id)
    
    # Filter files that have the query in their content preview
    query = query.lower()
    matching_files = []
    
    for file in files:
        content_preview = file.get('content_preview', '').lower()
        filename = file.get('name', '').lower()
        
        if query in content_preview or query in filename:
            matching_files.append(file)
            if len(matching_files) >= limit:
                break
                
    return matching_files

# Add enhanced file metadata to existing files
def enhance_existing_files(user_id):
    """
    Process existing files to add enhanced metadata
    Useful for upgrading older files in the database
    
    Args:
        user_id: The user ID to update files for
        
    Returns:
        Number of files updated
    """
    try:
        # Get user files
        files = get_user_files(user_id)
        if not files:
            return 0
            
        db = get_db()
        if not db:
            return 0
            
        updated_count = 0
        updated_files = []
        
        for file in files:
            # Skip files that already have enhanced metadata
            if 'content_preview' in file and file['content_preview']:
                updated_files.append(file)
                continue
                
            url = file.get('url')
            file_type = file.get('type')
            
            if url and file_type == 'pdf':
                # Download and process PDF
                temp_path = download_file(url)
                if temp_path:
                    try:
                        # Extract metadata
                        metadata = extract_pdf_metadata(temp_path)
                        content_preview = extract_text_preview(temp_path, max_chars=500)
                        file_hash = create_file_hash(temp_path)
                        
                        # Update file data
                        file['metadata'] = metadata
                        file['content_preview'] = content_preview
                        file['file_hash'] = file_hash
                        updated_files.append(file)
                        updated_count += 1
                        
                    finally:
                        # Clean up temp file
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                            
        # Update Firestore
        if updated_count > 0:
            db.collection('users').document(user_id).update({
                'files': updated_files
            })
            
        return updated_count
        
    except Exception as e:
        print(f"Error enhancing files: {e}")
        return 0

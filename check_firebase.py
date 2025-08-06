import firebase_admin
from firebase_admin import credentials, firestore
import sys
import json

def initialize_firebase():
    try:
        # Try to use existing app
        firebase_admin.get_app()
    except ValueError:
        # Initialize app if not already initialized
        try:
            # First try with service account file
            cred = credentials.Certificate("firebase_service_account.json")
            firebase_admin.initialize_app(cred)
            print("Firebase initialized with service account file")
        except Exception as e:
            # Fall back to application default credentials
            try:
                firebase_admin.initialize_app()
                print("Firebase initialized with default credentials")
            except Exception as e:
                print(f"Failed to initialize Firebase: {e}")
                sys.exit(1)

def list_users():
    """List all users in the database"""
    db = firestore.client()
    users_ref = db.collection("users")
    users = users_ref.stream()
    
    print("\n=== USERS ===")
    user_count = 0
    for user in users:
        user_count += 1
        print(f"User ID: {user.id}")
    
    if user_count == 0:
        print("No users found")
    else:
        print(f"\nTotal Users: {user_count}")

def user_details(user_id):
    """Show details for a specific user"""
    db = firestore.client()
    user_ref = db.collection("users").document(user_id)
    user = user_ref.get()
    
    if not user.exists:
        print(f"User {user_id} not found")
        return
    
    data = user.to_dict()
    
    print(f"\n=== USER {user_id} DETAILS ===")
    
    # Print notes
    notes = data.get("notes", [])
    print(f"\nNOTES ({len(notes)}):")
    for i, note in enumerate(notes, 1):
        print(f"  {i}. {note.get('content', 'No content')}")
    
    # Print tasks
    tasks = data.get("tasks", [])
    print(f"\nTASKS ({len(tasks)}):")
    for i, task in enumerate(tasks, 1):
        status = "✅" if task.get("completed") else "⏳"
        print(f"  {i}. {status} {task.get('task', 'No task description')}")
    
    # Print files
    files = data.get("files", [])
    print(f"\nFILES ({len(files)}):")
    for i, file in enumerate(files, 1):
        print(f"  {i}. {file.get('name', 'Unknown file')} ({file.get('type', 'unknown')})")

def display_help():
    print("""
Firebase Data Checker for TeleMind Bot

Usage:
  python check_firebase.py list              - List all users
  python check_firebase.py user <user_id>    - Show details for a specific user
    """)

if __name__ == "__main__":
    initialize_firebase()
    
    if len(sys.argv) < 2:
        display_help()
        sys.exit(0)
    
    command = sys.argv[1].lower()
    
    if command == "list":
        list_users()
    elif command == "user" and len(sys.argv) > 2:
        user_details(sys.argv[2])
    else:
        display_help()

import os
import firebase_admin
from firebase_admin import credentials, storage
import argparse

def check_firebase_storage():
    """Check if Firebase Storage is properly configured"""
    
    # Check for environment variables
    firebase_storage_bucket = os.getenv("FIREBASE_STORAGE_BUCKET")
    print(f"FIREBASE_STORAGE_BUCKET environment variable: {firebase_storage_bucket or 'Not set'}")
    
    try:
        # Check for service account file
        if os.path.exists("firebase_service_account.json"):
            print("Found firebase_service_account.json")
            cred = credentials.Certificate("firebase_service_account.json")
            try:
                # Initialize app with bucket
                if firebase_storage_bucket:
                    app = firebase_admin.initialize_app(cred, {
                        'storageBucket': firebase_storage_bucket
                    })
                else:
                    print("Warning: No bucket specified, using default from credentials")
                    app = firebase_admin.initialize_app(cred)
                
                # Try to get bucket
                bucket = storage.bucket()
                print(f"Successfully connected to Firebase Storage bucket: {bucket.name}")
                
                # List some files to verify access
                print("\nListing up to 5 files in bucket:")
                blobs = list(bucket.list_blobs(max_results=5))
                if blobs:
                    for blob in blobs:
                        print(f"- {blob.name}")
                else:
                    print("No files found (bucket may be empty)")
                    
                # Test creating a small file
                print("\nTesting file upload...")
                test_blob = bucket.blob("test-file.txt")
                test_blob.upload_from_string("This is a test file to verify Firebase Storage functionality.")
                test_blob.delete()  # Clean up after test
                print("Test upload successful!")
                
                return True
            except Exception as e:
                print(f"Error initializing Firebase with service account file: {e}")
                return False
        else:
            print("No firebase_service_account.json file found")
            
            # Try with environment variable
            print("\nAttempting to initialize Firebase with environment variables...")
            if "FIREBASE_SERVICE_ACCOUNT" in os.environ:
                print("FIREBASE_SERVICE_ACCOUNT environment variable is set")
                try:
                    import tempfile
                    import json
                    
                    # Create temp file from env var
                    fd, path = tempfile.mkstemp()
                    with os.fdopen(fd, 'w') as tmp:
                        tmp.write(os.environ["FIREBASE_SERVICE_ACCOUNT"])
                    
                    # Parse JSON to check content validity
                    with open(path, 'r') as f:
                        cred_json = json.load(f)
                        print(f"Service account JSON appears valid. Project ID: {cred_json.get('project_id', 'unknown')}")
                    
                    # Initialize Firebase
                    cred = credentials.Certificate(path)
                    if firebase_storage_bucket:
                        app = firebase_admin.initialize_app(cred, {
                            'storageBucket': firebase_storage_bucket
                        })
                    else:
                        app = firebase_admin.initialize_app(cred)
                    
                    # Clean up the temporary file
                    os.remove(path)
                    
                    # Try to get bucket
                    bucket = storage.bucket()
                    print(f"Successfully connected to Firebase Storage bucket: {bucket.name}")
                    return True
                except Exception as e:
                    print(f"Error initializing Firebase with environment variable: {e}")
                    return False
            else:
                print("FIREBASE_SERVICE_ACCOUNT environment variable is not set")
                return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Check Firebase Storage Configuration')
    parser.add_argument('--bucket', help='Override storage bucket name')
    args = parser.parse_args()
    
    # Set bucket from arguments if provided
    if args.bucket:
        os.environ["FIREBASE_STORAGE_BUCKET"] = args.bucket
        print(f"Using bucket from command line: {args.bucket}")
    
    # Run the check
    result = check_firebase_storage()
    if result:
        print("\n✅ Firebase Storage is properly configured.")
    else:
        print("\n❌ Firebase Storage is not properly configured.")
        print("\nTo fix:")
        print("1. Make sure you have a valid firebase_service_account.json file or FIREBASE_SERVICE_ACCOUNT environment variable")
        print("2. Set FIREBASE_STORAGE_BUCKET environment variable to your bucket name")
        print("3. Ensure the service account has permissions to access the bucket")

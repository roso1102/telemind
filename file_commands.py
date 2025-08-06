"""
File Listing Command for TeleMind Bot

This module adds a /files command to list user files with enhanced content previews
"""

async def handle_files_command(user_id, chat_id, args=None):
    """
    Handle the /files command to list user files
    
    Args:
        user_id: The Telegram user ID
        chat_id: The Telegram chat ID
        args: Optional command arguments (e.g., for filtering)
    """
    from firebase_storage_helper import get_user_files
    from main import send_message
    
    # Get user files
    file_type = args[0] if args and args[0] in ["pdf", "documents", "images"] else None
    files = get_user_files(user_id, file_type=file_type)
    
    if not files:
        await send_message(chat_id, "📭 You don't have any files yet.")
        return
    
    # Group files by type
    files_by_type = {}
    for file in files:
        file_type = file.get("type", "other")
        if file_type not in files_by_type:
            files_by_type[file_type] = []
        files_by_type[file_type].append(file)
    
    # Generate response
    reply = "🗂 *Your Files*:\n\n"
    
    # Process each file type
    for file_type, type_files in files_by_type.items():
        # Get emoji for file type
        type_emoji = "📄" if file_type == "pdf" or file_type == "documents" else "🖼" if file_type == "images" else "📁"
        
        reply += f"*{type_emoji} {file_type.capitalize()}*\n"
        
        # List files of this type
        for i, file in enumerate(type_files, 1):
            file_name = file.get("name", "Unnamed file")
            file_url = file.get("url", "#")
            
            # Add preview if available (for better context)
            preview = ""
            if file.get("content_preview"):
                # Truncate and clean up preview
                preview_text = file["content_preview"].replace("\n", " ").strip()
                if len(preview_text) > 80:
                    preview_text = preview_text[:77] + "..."
                preview = f"\n   _{preview_text}_"
                
            # Add upload date if available
            date_str = ""
            if file.get("timestamp"):
                date_str = f" ({file['timestamp']})"
            
            reply += f"{i}. [{file_name}]({file_url}){date_str}{preview}\n"
        
        reply += "\n"
    
    # Add help text
    reply += "\n*To reference a file, ask about it by name or content.*\n"
    reply += "For example: \"What does the marketing PDF say about customers?\""
    
    await send_message(chat_id, reply)

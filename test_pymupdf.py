import os
import fitz  # PyMuPDF
import sys

def extract_text_from_pdf(pdf_path, max_chars=10000, max_pages=None, chars_per_page=None):
    """
    Extract text from a PDF file using PyMuPDF with limits for token management.
    
    Args:
        pdf_path: Path to the PDF file
        max_chars: Maximum total characters to extract (default: 10000)
        max_pages: Maximum number of pages to process (default: all pages)
        chars_per_page: Maximum characters per page (default: no limit per page)
    """
    try:
        # Check if file exists
        if not os.path.exists(pdf_path):
            print(f"Error: File not found at {pdf_path}")
            return False

        # Open the PDF
        print(f"Opening PDF: {pdf_path}")
        doc = fitz.open(pdf_path)
        
        # Get document info
        print(f"\nDocument Information:")
        total_pages = len(doc)
        print(f"Number of pages: {total_pages}")
        
        if doc.metadata:
            print(f"Title: {doc.metadata.get('title', 'N/A')}")
            print(f"Author: {doc.metadata.get('author', 'N/A')}")
            print(f"Subject: {doc.metadata.get('subject', 'N/A')}")
            print(f"Producer: {doc.metadata.get('producer', 'N/A')}")
        
        # Apply page limit if specified
        if max_pages is None:
            max_pages = total_pages
        else:
            max_pages = min(max_pages, total_pages)
            
        print(f"Processing up to {max_pages} pages with {max_chars} character limit")
            
        # Extract text from each page with limits
        print("\nExtracting text from pages...")
        extracted_text = ""
        char_count = 0
        processed_pages = 0
        
        for page_num in range(max_pages):
            page = doc[page_num]
            text = page.get_text()
            
            # Apply per-page character limit if specified
            if chars_per_page is not None:
                text = text[:chars_per_page]
                
            # Print page preview
            print(f"\n--- Page {page_num + 1} ---")
            preview = text[:150].replace('\n', ' ').strip()
            if len(text) > 150:
                preview += "..."
            print(preview)
            
            # Add text to overall extraction
            page_text = text.strip()
            page_char_count = len(page_text)
            
            # Check if we'll exceed the character limit
            remaining_chars = max_chars - char_count
            if page_char_count > remaining_chars:
                # Only add text up to the limit
                extracted_text += page_text[:remaining_chars]
                char_count += remaining_chars
                processed_pages += 1
                print(f"Character limit reached ({max_chars}). Stopped at page {page_num + 1}.")
                break
            else:
                # Add the whole page text
                extracted_text += page_text + "\n\n"
                char_count += page_char_count
                processed_pages += 1
            
            # Check if we've hit the character limit
            if char_count >= max_chars:
                print(f"Character limit reached ({max_chars}). Stopped at page {page_num + 1}.")
                break
        
        print(f"\nText extraction complete! Processed {processed_pages} of {total_pages} pages.")
        print(f"Extracted {char_count} characters (limit: {max_chars})")
        
        # Calculate approximate tokens (rough estimate: ~4 chars per token for English text)
        estimated_tokens = char_count // 4
        print(f"Estimated tokens: ~{estimated_tokens}")
        
        return extracted_text
    
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    # Set up command line argument parsing
    parser = argparse.ArgumentParser(description='Extract text from a PDF file with limits')
    parser.add_argument('pdf_path', nargs='?', help='Path to the PDF file')
    parser.add_argument('--max-chars', type=int, default=10000, 
                        help='Maximum characters to extract (default: 10000)')
    parser.add_argument('--max-pages', type=int, 
                        help='Maximum pages to process (default: all)')
    parser.add_argument('--chars-per-page', type=int,
                        help='Maximum characters per page (default: no limit)')
    
    args = parser.parse_args()
    pdf_path = args.pdf_path
    
    # If no PDF path was provided via arguments
    if not pdf_path:
        # Look for any PDF in the current directory
        pdfs = [f for f in os.listdir('.') if f.lower().endswith('.pdf')]
        
        if pdfs:
            pdf_path = pdfs[0]
            print(f"No PDF path provided, using: {pdf_path}")
        else:
            pdf_path = input("Please enter the path to a PDF file: ")
    
    # Extract text with limits
    text = extract_text_from_pdf(
        pdf_path, 
        max_chars=args.max_chars, 
        max_pages=args.max_pages,
        chars_per_page=args.chars_per_page
    )
    
    # Save extracted text to a file for review (optional)
    output_file = pdf_path.replace('.pdf', '_extracted.txt')
    if text:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"\nExtracted text saved to: {output_file}")

import requests
import re
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bwriter import BibTexWriter
import json
import hashlib
from datetime import datetime

def extract_citations_from_wiki(wiki_url):
    """
    Extract citations from a MediaWiki page
    Returns a list of citations found
    """
    try:
        # Get the wiki page content
        response = requests.get(wiki_url)
        response.raise_for_status()
        content = response.text
        
        citations = []
        
        # Pattern 1: <ref>...</ref> tags
        ref_pattern = r'<ref[^>]*>(.*?)</ref>'
        ref_matches = re.findall(ref_pattern, content, re.DOTALL | re.IGNORECASE)
        
        for match in ref_matches:
            # Clean up the reference text
            clean_ref = re.sub(r'<[^>]+>', '', match)  # Remove HTML tags
            clean_ref = clean_ref.strip()
            if clean_ref and len(clean_ref) > 10:  # Only keep substantial references
                citations.append({
                    'type': 'ref_tag',
                    'content': clean_ref,
                    'source_url': wiki_url
                })
        
        # Pattern 2: {{cite ...}} templates
        cite_pattern = r'\{\{cite\s+[^}]+\}\}'
        cite_matches = re.findall(cite_pattern, content, re.IGNORECASE)
        
        for match in cite_matches:
            citations.append({
                'type': 'cite_template',
                'content': match.strip(),
                'source_url': wiki_url
            })
        
        # Pattern 3: [https://...] external links with titles
        link_pattern = r'\[https?://[^\s\]]+\s+([^\]]+)\]'
        link_matches = re.findall(link_pattern, content)
        
        for match in link_matches:
            if len(match.strip()) > 5:  # Only meaningful titles
                citations.append({
                    'type': 'external_link',
                    'content': match.strip(),
                    'source_url': wiki_url
                })
        
        return citations
        
    except Exception as e:
        print(f"Error extracting citations from {wiki_url}: {str(e)}")
        return []

def load_existing_bib(bib_file_path):
    """
    Load existing .bib file and return parsed entries
    """
    try:
        with open(bib_file_path, 'r', encoding='utf-8') as bib_file:
            parser = BibTexParser(common_strings=True)
            bib_database = bibtexparser.load(bib_file, parser=parser)
            return bib_database
    except Exception as e:
        print(f"Error loading .bib file: {str(e)}")
        return BibDatabase()

def create_citation_key(citation_text):
    """
    Create a unique citation key from citation text
    """
    # Create a simple hash-based key
    hash_object = hashlib.md5(citation_text.encode())
    hash_hex = hash_object.hexdigest()[:8]
    return f"wiki_{hash_hex}"

def citation_exists_in_bib(citation, bib_database):
    """
    Check if a citation already exists in the .bib database
    Returns True if found, False otherwise
    """
    citation_text = citation['content'].lower()
    
    # Check against titles and other fields
    for entry in bib_database.entries:
        # Check title
        if 'title' in entry:
            if citation_text in entry['title'].lower() or entry['title'].lower() in citation_text:
                return True
        
        # Check other fields that might match
        for field in ['author', 'journal', 'booktitle', 'note']:
            if field in entry:
                if citation_text in entry[field].lower() or entry[field].lower() in citation_text:
                    return True
    
    return False

def create_bib_entry_from_citation(citation):
    """
    Create a new .bib entry from a wiki citation
    """
    citation_key = create_citation_key(citation['content'])
    
    # Create basic entry structure
    entry = {
        'ID': citation_key,
        'ENTRYTYPE': 'misc',  # Default type for unknown citations
        'title': citation['content'][:200] + ('...' if len(citation['content']) > 200 else ''),
        'note': f"Extracted from wiki citation: {citation['type']}",
        'url': citation['source_url'],
        'tags': 'source:wikiversity',
        'extra': f"Cited on: {citation['source_url']}"
    }
    
    # Try to extract more specific information based on citation type
    if citation['type'] == 'cite_template':
        # Parse cite template for more details
        content = citation['content']
        
        # Extract title if present
        title_match = re.search(r'title\s*=\s*([^|}\n]+)', content, re.IGNORECASE)
        if title_match:
            entry['title'] = title_match.group(1).strip()
        
        # Extract author if present
        author_match = re.search(r'author\s*=\s*([^|}\n]+)', content, re.IGNORECASE)
        if author_match:
            entry['author'] = author_match.group(1).strip()
        
        # Extract year if present
        year_match = re.search(r'year\s*=\s*([^|}\n]+)', content, re.IGNORECASE)
        if year_match:
            entry['year'] = year_match.group(1).strip()
        
        # Extract journal if present
        journal_match = re.search(r'journal\s*=\s*([^|}\n]+)', content, re.IGNORECASE)
        if journal_match:
            entry['journal'] = journal_match.group(1).strip()
            entry['ENTRYTYPE'] = 'article'
    
    return entry

def save_updated_bib(bib_database, output_path):
    """
    Save the updated .bib database to file
    """
    try:
        writer = BibTexWriter()
        writer.indent = '  '  # Nice formatting
        
        with open(output_path, 'w', encoding='utf-8') as bib_file:
            bibtexparser.dump(bib_database, bib_file, writer=writer)
        
        return True
    except Exception as e:
        print(f"Error saving .bib file: {str(e)}")
        return False

def main():
    """
    Main function to sync wiki citations with Zotero .bib file
    """
    # Configuration - you'll need to update these
    wiki_urls = [
        "https://en.wikiversity.org/wiki/AIXworkbench/Papers/Building-the-Workbench"
    ]
    
    bib_file_path = "references.bib"  # Path to your .bib file
    
    print("Starting wiki citation sync...")
    
    # Load existing .bib file
    print("Loading existing .bib file...")
    bib_database = load_existing_bib(bib_file_path)
    initial_count = len(bib_database.entries)
    print(f"Found {initial_count} existing entries in .bib file")
    
    new_entries_added = 0
    
    # Process each wiki page
    for wiki_url in wiki_urls:
        print(f"\nProcessing wiki page: {wiki_url}")
        
        # Extract citations from the wiki page
        citations = extract_citations_from_wiki(wiki_url)
        print(f"Found {len(citations)} potential citations")
        
        # Check each citation against existing .bib entries
        for citation in citations:
            if not citation_exists_in_bib(citation, bib_database):
                print(f"Adding new citation: {citation['content'][:50]}...")
                
                # Create new .bib entry
                new_entry = create_bib_entry_from_citation(citation)
                bib_database.entries.append(new_entry)
                new_entries_added += 1
            else:
                print(f"Citation already exists, skipping: {citation['content'][:50]}...")
    
    # Save updated .bib file
    if new_entries_added > 0:
        print(f"\nAdding {new_entries_added} new entries to .bib file...")
        if save_updated_bib(bib_database, bib_file_path):
            print("Successfully updated .bib file!")
        else:
            print("Error saving updated .bib file")
    else:
        print("\nNo new citations found. .bib file unchanged.")
    
    print(f"Sync complete. Total entries: {len(bib_database.entries)}")

if __name__ == "__main__":
    main()

import requests
import re
import json
import hashlib
import os
import time
from datetime import datetime
from urllib.parse import quote

class ZoteroAPI:
    def __init__(self, api_key, user_id):
        self.api_key = api_key
        self.user_id = user_id
        self.base_url = f"https://api.zotero.org/users/{user_id}"
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
    
    def get_all_items(self):
        """Get all items from Zotero library"""
        all_items = []
        start = 0
        limit = 100
        
        while True:
            url = f"{self.base_url}/items"
            params = {
                'start': start,
                'limit': limit,
                'format': 'json',
                'include': 'data'
            }
            
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code != 200:
                print(f"Error fetching items: {response.status_code}")
                break
                
            items = response.json()
            if not items:
                break
                
            all_items.extend(items)
            start += limit
            
            # Rate limiting - Zotero API allows 120 requests per minute
            time.sleep(0.5)
        
        return all_items
    
    def create_item(self, item_data):
        """Create a new item in Zotero"""
        url = f"{self.base_url}/items"
        
        response = requests.post(url, headers=self.headers, data=json.dumps([item_data]))
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error creating item: {response.status_code} - {response.text}")
            return None
    
    def add_tags_to_item(self, item_key, tags):
        """Add tags to an existing item"""
        # Get current item data
        url = f"{self.base_url}/items/{item_key}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            return False
            
        item_data = response.json()
        
        # Add new tags
        existing_tags = item_data['data'].get('tags', [])
        for tag in tags:
            if not any(t['tag'] == tag for t in existing_tags):
                existing_tags.append({'tag': tag})
        
        item_data['data']['tags'] = existing_tags
        
        # Update item
        update_response = requests.put(url, headers=self.headers, data=json.dumps(item_data['data']))
        return update_response.status_code == 204

def extract_citations_from_wiki(wiki_url):
    """Extract citations from a MediaWiki page"""
    try:
        response = requests.get(wiki_url)
        response.raise_for_status()
        content = response.text
        
        citations = []
        
        # Pattern 1: <ref>...</ref> tags
        ref_pattern = r'<ref[^>]*>(.*?)</ref>'
        ref_matches = re.findall(ref_pattern, content, re.DOTALL | re.IGNORECASE)
        
        for match in ref_matches:
            clean_ref = re.sub(r'<[^>]+>', '', match).strip()
            if clean_ref and len(clean_ref) > 10:
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
            if len(match.strip()) > 5:
                citations.append({
                    'type': 'external_link',
                    'content': match.strip(),
                    'source_url': wiki_url
                })
        
        return citations
        
    except Exception as e:
        print(f"Error extracting citations from {wiki_url}: {str(e)}")
        return []

def citation_exists_in_zotero(citation, zotero_items):
    """Check if a citation already exists in Zotero"""
    citation_text = citation['content'].lower()
    
    for item in zotero_items:
        item_data = item.get('data', {})
        
        # Check title
        title = item_data.get('title', '').lower()
        if title and (citation_text in title or title in citation_text):
            return True
        
        # Check abstract/note
        abstract = item_data.get('abstractNote', '').lower()
        if abstract and (citation_text in abstract or abstract in citation_text):
            return True
        
        # Check extra field
        extra = item_data.get('extra', '').lower()
        if extra and citation_text in extra:
            return True
    
    return False

def parse_cite_template(cite_template):
    """Parse a MediaWiki cite template into structured data"""
    data = {}
    
    # Remove the outer braces and 'cite' part
    content = re.sub(r'^\{\{cite\s+\w+\s*\|?', '', cite_template, flags=re.IGNORECASE)
    content = re.sub(r'\}\}$', '', content)
    
    # Split by | but be careful about nested templates
    parts = []
    current_part = ""
    brace_count = 0
    
    for char in content:
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
        elif char == '|' and brace_count == 0:
            parts.append(current_part.strip())
            current_part = ""
            continue
        current_part += char
    
    if current_part.strip():
        parts.append(current_part.strip())
    
    # Parse each part
    for part in parts:
        if '=' in part:
            key, value = part.split('=', 1)
            key = key.strip().lower()
            value = value.strip()
            
            # Map common cite template fields to Zotero fields
            field_mapping = {
                'title': 'title',
                'author': 'creators',
                'year': 'date',
                'journal': 'publicationTitle',
                'volume': 'volume',
                'issue': 'issue',
                'pages': 'pages',
                'doi': 'DOI',
                'url': 'url',
                'publisher': 'publisher',
                'isbn': 'ISBN'
            }
            
            if key in field_mapping:
                if key == 'author':
                    # Handle author field specially
                    authors = [{'creatorType': 'author', 'name': value}]
                    data['creators'] = authors
                else:
                    data[field_mapping[key]] = value
    
    return data

def create_zotero_item_from_citation(citation):
    """Create a Zotero item from a wiki citation"""
    base_item = {
        'itemType': 'webpage',
        'title': '',
        'creators': [],
        'tags': [{'tag': 'source:wikiversity'}],
        'extra': f"Cited on: {citation['source_url']}\nExtracted from: {citation['type']}"
    }
    
    if citation['type'] == 'cite_template':
        # Parse cite template for structured data
        parsed_data = parse_cite_template(citation['content'])
        base_item.update(parsed_data)
        
        # Determine item type based on parsed data
        if 'publicationTitle' in parsed_data:
            base_item['itemType'] = 'journalArticle'
        elif 'publisher' in parsed_data:
            base_item['itemType'] = 'book'
        
        # Use parsed title or fall back to truncated content
        if not base_item.get('title'):
            base_item['title'] = citation['content'][:200]
    
    elif citation['type'] == 'ref_tag':
        # Try to extract basic info from ref tag content
        content = citation['content']
        
        # Look for patterns like "Author (Year). Title."
        author_year_match = re.search(r'^([^(]+)\s*\((\d{4})\)', content)
        if author_year_match:
            author_name = author_year_match.group(1).strip()
            year = author_year_match.group(2)
            
            base_item['creators'] = [{'creatorType': 'author', 'name': author_name}]
            base_item['date'] = year
        
        base_item['title'] = content[:200] + ('...' if len(content) > 200 else '')
    
    elif citation['type'] == 'external_link':
        base_item['title'] = citation['content']
        base_item['itemType'] = 'webpage'
    
    # Ensure title is not empty
    if not base_item.get('title'):
        base_item['title'] = citation['content'][:100] + ('...' if len(citation['content']) > 100 else '')
    
    return base_item

def export_to_bib(zotero_items, output_file):
    """Export Zotero items to BibTeX format"""
    try:
        # This is a simplified BibTeX export
        # In a real implementation, you might want to use a proper BibTeX library
        with open(output_file, 'w', encoding='utf-8') as f:
            for item in zotero_items:
                data = item.get('data', {})
                item_type = data.get('itemType', 'misc')
                key = item.get('key', 'unknown')
                
                # Map Zotero item types to BibTeX types
                type_mapping = {
                    'journalArticle': 'article',
                    'book': 'book',
                    'bookSection': 'inbook',
                    'conferencePaper': 'inproceedings',
                    'webpage': 'misc',
                    'thesis': 'phdthesis'
                }
                
                bib_type = type_mapping.get(item_type, 'misc')
                
                f.write(f"@{bib_type}{{{key},\n")
                
                # Write fields
                if data.get('title'):
                    f.write(f"  title = {{{data['title']}}},\n")
                
                if data.get('creators'):
                    authors = []
                    for creator in data['creators']:
                        if creator.get('firstName') and creator.get('lastName'):
                            authors.append(f"{creator['lastName']}, {creator['firstName']}")
                        elif creator.get('name'):
                            authors.append(creator['name'])
                    if authors:
                        f.write(f"  author = {{{' and '.join(authors)}}},\n")
                
                if data.get('date'):
                    f.write(f"  year = {{{data['date']}}},\n")
                
                if data.get('publicationTitle'):
                    f.write(f"  journal = {{{data['publicationTitle']}}},\n")
                
                if data.get('url'):
                    f.write(f"  url = {{{data['url']}}},\n")
                
                f.write("}\n\n")
        
        return True
    except Exception as e:
        print(f"Error exporting to BibTeX: {str(e)}")
        return False

def main():
    """Main function"""
    # Get credentials from environment variables
    api_key = os.getenv('ZOTERO_API_KEY')
    user_id = os.getenv('ZOTERO_USER_ID')
    
    if not api_key or not user_id:
        print("Error: ZOTERO_API_KEY and ZOTERO_USER_ID environment variables must be set")
        return
    
    # Configuration
    wiki_urls = [
        "https://en.wikiversity.org/wiki/AIXworkbench/Papers/Building-the-Workbench",
        # Add more wiki URLs here
    ]
    
    print("Starting automated Zotero-Wiki sync...")
    
    # Initialize Zotero API
    zotero = ZoteroAPI(api_key, user_id)
    
    # Get all existing items from Zotero
    print("Fetching existing Zotero items...")
    zotero_items = zotero.get_all_items()
    print(f"Found {len(zotero_items)} existing items in Zotero")
    
    new_items_added = 0
    
    # Process each wiki page
    for wiki_url in wiki_urls:
        print(f"\nProcessing wiki page: {wiki_url}")
        
        # Extract citations
        citations = extract_citations_from_wiki(wiki_url)
        print(f"Found {len(citations)} potential citations")
        
        # Check each citation
        for citation in citations:
            if not citation_exists_in_zotero(citation, zotero_items):
                print(f"Adding new citation: {citation['content'][:50]}...")
                
                # Create Zotero item
                item_data = create_zotero_item_from_citation(citation)
                result = zotero.create_item(item_data)
                
                if result:
                    new_items_added += 1
                    print("✓ Successfully added to Zotero")
                else:
                    print("✗ Failed to add to Zotero")
                
                # Rate limiting
                time.sleep(1)
            else:
                print(f"Citation already exists: {citation['content'][:50]}...")
    
    # Export updated library to BibTeX
    print(f"\nSync complete! Added {new_items_added} new items.")
    
    if new_items_added > 0:
        print("Fetching updated library and exporting to BibTeX...")
        updated_items = zotero.get_all_items()
        if export_to_bib(updated_items, 'references.bib'):
            print("✓ Successfully exported to references.bib")
        else:
            print("✗ Failed to export to BibTeX")
    else:
        print("No new items to export.")

if __name__ == "__main__":
    main()

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import time

queries = [
    ('search1.json', 'abs:"large language model" AND abs:game AND abs:agent'),
    ('search2.json', 'abs:"game playing" AND abs:"language model"'),
    ('search3.json', 'ti:"game agent" AND abs:"LLM"'),
    ('search4.json', 'abs:"computer use" AND abs:agent AND abs:game'),
    ('search5.json', 'abs:Minecraft AND abs:"language model" AND abs:agent'),
    ('search6.json', 'abs:"multimodal agent" AND abs:game'),
    ('search7.json', 'abs:"game environment" AND abs:"reinforcement learning" AND abs:"language model"'),
    ('search8.json', 'ti:Voyager OR ti:SIMA OR ti:Genie AND abs:game AND abs:agent'),
    ('search9.json', 'abs:"tool use" AND abs:agent AND abs:game'),
    ('search10.json', 'abs:"model context protocol" OR abs:MCP AND abs:agent')
]

out_dir = r"C:\Users\david\Desktop\Projects\gaming-mcp\research\arxiv"

for filename, query in queries:
    print(f"Fetching {filename}...")
    encoded_query = urllib.parse.quote(query)
    url = f"http://export.arxiv.org/api/query?search_query={encoded_query}&max_results=10&sortBy=submittedDate&sortOrder=descending"
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
        
        entries = []
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text.replace('\n', ' ').strip()
            summary = entry.find('atom:summary', ns).text.replace('\n', ' ').strip()
            published = entry.find('atom:published', ns).text
            authors = [author.find('atom:name', ns).text for author in entry.findall('atom:author', ns)]
            entry_id = entry.find('atom:id', ns).text
            
            entries.append({
                "title": title,
                "summary": summary,
                "published": published,
                "authors": authors,
                "id": entry_id,
                "pdf_url": entry_id
            })
            
        with open(rf"{out_dir}\{filename}", "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
            
    except Exception as e:
        print(f"Error on {filename}:", e)
        
    time.sleep(3) # Polite delay

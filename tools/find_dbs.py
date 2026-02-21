import os
import json
import httpx
from dotenv import load_dotenv

def find_status_via_search():
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    
    url = "https://api.notion.com/v1/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    payload = {
        "filter": {"value": "database", "property": "object"}
    }
    
    with httpx.Client() as client:
        resp = client.post(url, headers=headers, json=payload)
        databases = resp.json().get("results", [])
        
    for db in databases:
        print(f"DB Title: {db.get('title', [{}])[0].get('plain_text', 'Untitled')}")
        print(f"DB ID: {db['id']}")
        print("Properties:")
        for name, prop in db.get("properties", {}).items():
            print(f"  - {name}: {prop['type']}")
        print("-" * 20)

if __name__ == "__main__":
    find_status_via_search()

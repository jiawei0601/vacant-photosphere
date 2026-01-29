import os
import json
import httpx
from dotenv import load_dotenv
import sys

# 強制設定輸出編碼
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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
        
    print(json.dumps(databases, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    find_status_via_search()

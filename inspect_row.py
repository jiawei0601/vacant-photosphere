import os
import json
import httpx
from dotenv import load_dotenv

def find_status():
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    db_id = os.getenv("INVENTORY_DATABASE_ID")
    
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    with httpx.Client() as client:
        resp = client.post(url, headers=headers, json={"page_size": 1})
        data = resp.json()
    
    if data.get("results"):
        props = data["results"][0]["properties"]
        print(json.dumps(props, indent=2, ensure_ascii=False))
    else:
        print("No rows found in database to inspect properties.")

if __name__ == "__main__":
    find_status()

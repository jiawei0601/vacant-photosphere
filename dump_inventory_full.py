import os
import json
import httpx
from dotenv import load_dotenv
import sys

# 強制設定輸出編碼
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def dump_schema():
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    db_id = os.getenv("INVENTORY_DATABASE_ID")
    
    url = f"https://api.notion.com/v1/databases/{db_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28"
    }
    
    with httpx.Client() as client:
        resp = client.get(url, headers=headers)
        data = resp.json()
    
    print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    dump_schema()

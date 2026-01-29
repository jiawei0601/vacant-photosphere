import os
import json
import httpx
from dotenv import load_dotenv
import sys

# 強制設定輸出編碼
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_manual_create():
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    db_id = os.getenv("INVENTORY_DATABASE_ID")
    
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    # 測試不同可能的欄位名稱
    test_cases = [
        {"名稱": "台積電", "代碼": "2330"},
        {"股票名稱": "台積電", "代碼": "2330"},
        {"Name": "台積電", "Symbol": "2330"}
    ]
    
    for case in test_cases:
        print(f"Testing case: {case}")
        props = {}
        for k, v in case.items():
             if k in ["名稱", "股票名稱", "Name"]:
                 props[k] = {"title": [{"text": {"content": v}}]}
             else:
                 props[k] = {"rich_text": [{"text": {"content": v}}]}
        
        payload = {
            "parent": {"database_id": db_id},
            "properties": props
        }
        
        with httpx.Client() as client:
            resp = client.post(url, headers=headers, json=payload)
            print(f"Result: {resp.status_code}")
            if resp.status_code != 200:
                print(resp.text)
            else:
                print("✅ Success!")
                break

if __name__ == "__main__":
    test_manual_create()

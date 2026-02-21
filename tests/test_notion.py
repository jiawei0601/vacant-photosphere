import os
from notion_helper import NotionHelper
from dotenv import load_dotenv

def test_notion_upsert():
    # 載入環境變數
    load_dotenv()
    
    # 初始化 NotionHelper
    helper = NotionHelper()
    
    # 測試資料
    test_items = [
        {"symbol": "2330", "name": "測試-台積電"},
        {"symbol": "240326", "name": "測試-權證標的"},
        {"symbol": "00738U", "name": "測試-字母標的"}
    ]
    
    print("=== 開始 Notion 寫入測試 ===")
    print(f"Token 長度: {len(helper.token) if helper.token else 0}")
    print(f"庫存資料庫 ID: {helper.inventory_database_id}")
    
    if not helper.inventory_database_id:
        print("❌ 錯誤: 未設定 INVENTORY_DATABASE_ID 環境變數")
        return

    for item in test_items:
        print(f"\n正在嘗試寫入: {item['name']} ({item['symbol']})...")
        success = helper.upsert_inventory_item(item['symbol'], item['name'])
        if success:
            print(f"✅ {item['symbol']} 測試執行通過 (請檢查 Notion 資料庫是否出現資料)")
        else:
            print(f"❌ {item['symbol']} 測試執行失敗 (請檢查終端機報錯日誌)")

if __name__ == "__main__":
    test_notion_upsert()

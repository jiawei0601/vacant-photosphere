import os
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()

class NotionHelper:
    def __init__(self):
        self.token = os.getenv("NOTION_TOKEN", "").strip()
        self.database_id = os.getenv("NOTION_DATABASE_ID", "").strip()
        self.inventory_database_id = os.getenv("INVENTORY_DATABASE_ID", "").strip()
        if self.token:
            self.notion = Client(auth=self.token)
        else:
            self.notion = None

    def get_monitoring_list(self):
        """
        從 Notion 資料庫獲取所有監控標的
        """
        if not self.notion:
            print("Notion 未設定，無法讀取資料")
            return []

        try:
            import httpx
            results = []
            url = f"https://api.notion.com/v1/databases/{self.database_id}/query"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json"
            }
            
            with httpx.Client() as client:
                resp = client.post(url, headers=headers)
                resp.raise_for_status()
                query = resp.json()

            for page in query.get("results", []):
                props = page.get("properties", {})
                
                # 提取欄位內容
                # 注意：Notion API 的欄位名稱必須與資料庫一致
                name = self._get_title(props, "名稱")
                symbol = self._get_text(props, "代碼")
                high_alert = self._get_number(props, "上限警戒值")
                low_alert = self._get_number(props, "下限警戒值")
                current_price = self._get_number(props, "當前價格")
                status = self._get_status(props, "狀態")
                
                if symbol:
                    results.append({
                        "page_id": page["id"],
                        "name": name,
                        "symbol": symbol,
                        "current_price": current_price,
                        "high_alert": high_alert,
                        "low_alert": low_alert,
                        "status": status
                    })
            return results
        except Exception as e:
            print(f"查詢 Notion 資料庫時發生錯誤: {e}")
            return []

    def update_price_and_status(self, page_id, current_price, status_name):
        """
        更新 Notion 頁面的當前價格與狀態
        """
        if not self.notion:
            return

        try:
            # 根據 dump_notion_schema.py 的結果，'狀態' 是 status 類型
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    "當前價格": {"number": current_price},
                    "狀態": {"status": {"name": status_name}},
                    "更新時間": {"date": {"start": self._get_now_iso()}}
                }
            )
        except Exception as e:
            print(f"更新 Notion 頁面 {page_id} 時發生錯誤: {e}")

    def _get_title(self, props, name):
        title_obj = props.get(name, {}).get("title", [])
        return title_obj[0].get("plain_text", "") if title_obj else ""

    def _get_text(self, props, name):
        rich_text = props.get(name, {}).get("rich_text", [])
        return rich_text[0].get("plain_text", "") if rich_text else ""

    def _get_number(self, props, name):
        return props.get(name, {}).get("number")

    def _get_status(self, props, name):
        return props.get(name, {}).get("status", {}).get("name", "正常")

    def _get_now_iso(self):
        from datetime import datetime, timezone, timedelta
        # 轉換為台灣時間 (UTC+8)
        tw_time = datetime.now(timezone(timedelta(hours=8)))
        return tw_time.isoformat()

    def upsert_inventory_item(self, symbol, name, date_str=None):
        """
        更新或新增庫存資料庫項
        """
        if not self.notion:
            print("❌ Notion Client 未初始化")
            return False
        if not self.inventory_database_id:
            print("⚠️ 警告: INVENTORY_DATABASE_ID 未設定，跳過庫存更新")
            return False

        target_date = date_str if date_str else self._get_now_iso()
        # 如果傳入的是 YYYY-MM-DD，轉成 ISO 格式
        if date_str and len(date_str) == 10:
             target_date = f"{date_str}T00:00:00.000+08:00"

        try:
            # 1. 查詢是否已存在
            query = self.notion.databases.query(
                database_id=self.inventory_database_id,
                filter={
                    "property": "代碼",
                    "rich_text": {"equals": symbol}
                }
            )

            if query.get("results"):
                # 已存在，更新日期或狀態
                page_id = query["results"][0]["id"]
                self.notion.pages.update(
                    page_id=page_id,
                    properties={
                        "更新時間": {"date": {"start": target_date}},
                        "狀態": {"status": {"name": "庫存中"}}
                    }
                )
                print(f"✅ 更新庫存成功: {name} ({symbol})")
            else:
                # 不存在，新增
                self.notion.pages.create(
                    parent={"database_id": self.inventory_database_id},
                    properties={
                        "名稱": {"title": [{"text": {"content": name}}]},
                        "代碼": {"rich_text": [{"text": {"content": symbol}}]},
                        "更新時間": {"date": {"start": target_date}},
                        "狀態": {"status": {"name": "庫存中"}}
                    }
                )
                print(f"✅ 新增庫存成功: {name} ({symbol})")
            return True
        except Exception as e:
            print(f"❌ 操作 Notion 庫存資料庫時發生錯誤 ({symbol}): {e}")
            return False

    def update_alert_prices(self, page_id, high_alert=None, low_alert=None):
        """
        更新 Notion 頁面的警戒價格
        """
        if not self.notion:
            return

        properties = {}
        if high_alert is not None:
            properties["上限警戒值"] = {"number": high_alert}
        if low_alert is not None:
            properties["下限警戒值"] = {"number": low_alert}

        if not properties:
            return

        try:
            self.notion.pages.update(
                page_id=page_id,
                properties=properties
            )
            print(f"成功更新 Notion 警戒值: {properties}")
        except Exception as e:
            print(f"更新 Notion 警戒值時發生錯誤: {e}")

if __name__ == "__main__":
    # 簡單測試
    helper = NotionHelper()
    if os.getenv("NOTION_TOKEN"):
        items = helper.get_monitoring_list()
        print(f"讀取到 {len(items)} 個監控標的:")
        for item in items:
            print(f"- {item['name']} ({item['symbol']}): High={item['high_alert']}, Low={item['low_alert']}")
    else:
        print("請在 .env 中設定 Notion Token 後再測試")

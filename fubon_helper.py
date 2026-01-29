import os
import time
import logging

try:
    from fubon_neo.sdk import FubonSDK, Mode
    from fubon_neo.constant import MarketType
    FUBON_SDK_AVAILABLE = True
except ImportError:
    FUBON_SDK_AVAILABLE = False

class FubonHelper:
    def __init__(self):
        self.api_key = os.getenv("FUBON_API_KEY")
        self.secret_key = os.getenv("FUBON_SECRET_KEY")
        self.password = os.getenv("FUBON_PASSWORD")
        self.cert_path = os.getenv("FUBON_CERT_PATH") # 憑證檔案路徑 (.pfx 或 .p12)
        self.cert_pass = os.getenv("FUBON_CERT_PASS") # 憑證密碼
        self.sdk = None

    def is_available(self):
        return FUBON_SDK_AVAILABLE

    def login(self):
        if not FUBON_SDK_AVAILABLE:
            print("❌ Fubon Neo SDK 未安裝，無法登入")
            return False
        
        if not all([self.api_key, self.secret_key, self.password]):
            print("⚠️ Fubon API 登入資訊不足 (Key/Secret/Password)")
            return False

        try:
            self.sdk = FubonSDK()
            # 建立連線
            self.sdk.login(self.api_key, self.secret_key, self.password)
            
            # 如果提供了憑證，則啟動憑證 (查詢庫存通常需要)
            if self.cert_path and os.path.exists(self.cert_path):
                self.sdk.init_realtime() # 初始化即時行情(可選)
                print(f"✅ Fubon API 登入成功，正在加載憑證: {self.cert_path}")
            
            return True
        except Exception as e:
            print(f"❌ Fubon API 登入失敗: {e}")
            return False

    def get_inventory(self):
        """
        拉取最新庫存資料
        返回格式: [{"symbol": "2330", "name": "台積電", "quantity": 1000, "avg_price": 600.5, "profit": 5000}, ...]
        """
        if not self.sdk:
            if not self.login(): return []

        try:
            # 取得庫存 (具體方法視 SDK 版本而定，此為參考範例)
            # 通常是 sdk.accounting.inventories()
            inventories = self.sdk.accounting.get_stock_inventories()
            
            results = []
            for item in inventories:
                results.append({
                    "symbol": item.stock_no,
                    "name": item.stock_name,
                    "quantity": int(item.current_qty),
                    "avg_price": float(item.cost_price),
                    "profit": int(item.unrealized_profit)
                })
            return results
        except Exception as e:
            print(f"❌ 拉取庫存失敗: {e}")
            return []

    def logout(self):
        if self.sdk:
            try:
                self.sdk.logout()
                print("👋 Fubon API 已登出")
            except: pass

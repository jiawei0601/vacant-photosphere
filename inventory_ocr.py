import re
import os
import json
import io
from google.cloud import vision
from google.oauth2 import service_account

class InventoryOCR:
    def __init__(self):
        """
        初始化 Google Cloud Vision OCR 讀取器
        需設定環境變數 GOOGLE_SERVICE_ACCOUNT_JSON (JSON 內容) 
        或 GOOGLE_APPLICATION_CREDENTIALS (檔案路徑)
        """
        self.client = self._init_client()

    def _init_client(self):
        # 1. 優先檢查 JSON 內容環境變數 (適合 Railway 部署)
        service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if service_account_json:
            try:
                info = json.loads(service_account_json)
                credentials = service_account.Credentials.from_service_account_info(info)
                print("✅ 已從 GOOGLE_SERVICE_ACCOUNT_JSON 環境變數初始化 Google Vision Client")
                return vision.ImageAnnotatorClient(credentials=credentials)
            except Exception as e:
                print(f"❌ 解析 GOOGLE_SERVICE_ACCOUNT_JSON 失敗: {e}")

        # 2. 次要檢查檔案路徑環境變數
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if credentials_path and os.path.exists(credentials_path):
            print(f"✅ 已從檔案 {credentials_path} 初始化 Google Vision Client")
            return vision.ImageAnnotatorClient()

        print("⚠️ 警告: 未找到 Google Cloud 認證資訊，OCR 功能將無法運作。")
        return None

    def process_image(self, image_path):
        """
        處理圖片並提取文字 (使用 Google Cloud Vision)
        """
        if not self.client:
            print("OCR Client 未初始化")
            return []

        if not os.path.exists(image_path):
            print(f"找不到圖片: {image_path}")
            return []

        try:
            print(f"正在透過 Google Cloud Vision 解析圖片: {image_path}")
            with io.open(image_path, 'rb') as image_file:
                content = image_file.read()

            image = vision.Image(content=content)
            # 執行文字辨識 (支援繁體中文)
            response = self.client.text_detection(image=image)
            texts = response.text_annotations

            if response.error.message:
                raise Exception(f"{response.error.message}")

            if not texts:
                return []

            # 第 0 個元素是完整文字區塊，後續是個別行/單字
            extracted_text = []
            # 跳過第一個 (全選區塊)，從索引 1 開始獲取個別偵測到的文字
            for annotation in texts[1:]:
                extracted_text.append({
                    "text": annotation.description.strip(),
                    # Google Vision 不直接提供類似 EasyOCR 的 per-word prob，通常精準度很高
                    "confidence": 1.0, 
                    # 邊界框 (Vertices)
                    "bbox": [(v.x, v.y) for v in annotation.bounding_poly.vertices]
                })

            return extracted_text

        except Exception as e:
            print(f"❌ Google Vision OCR 執行錯誤: {e}")
            return []

    def extract_stock_info(self, image_path):
        """
        從文字中分析股票代碼與名稱
        """
        data = self.process_image(image_path)
        if not data:
            return []
            
        # 台灣股票代碼通常為 4 位數字，有時 5-6 位
        symbol_pattern = re.compile(r'\b\d{4,6}\b')
        found_stocks = {}
        
        for i, item in enumerate(data):
            text = item['text']
            match = symbol_pattern.search(text)
            if match:
                symbol = match.group()
                
                # 嘗試尋找名稱：通常在代碼的前面或後面一個索引
                name = ""
                # 向前找
                if i > 0:
                    prev_text = data[i-1]['text']
                    if any('\u4e00' <= char <= '\u9fff' for char in prev_text):
                        name = prev_text
                # 向後找
                if not name and i < len(data) - 1:
                    next_text = data[i+1]['text']
                    if any('\u4e00' <= char <= '\u9fff' for char in next_text):
                        name = next_text
                
                # 清理名稱中的非中文字元
                name = re.sub(r'[^\u4e00-\u9fff]', '', name)
                
                if symbol not in found_stocks:
                    found_stocks[symbol] = name
        
        results = []
        for symbol, name in found_stocks.items():
            results.append({
                "symbol": symbol,
                "name": name if name else "未知名稱"
            })
            
        return results

if __name__ == "__main__":
    # 簡單測試指令
    import sys
    if len(sys.argv) > 1:
        ocr = InventoryOCR()
        stocks = ocr.extract_stock_info(sys.argv[1])
        print("解析結果:")
        for s in stocks:
            print(f"- {s['name']} ({s['symbol']})")
    else:
        print("使用方式: python inventory_ocr.py <image_path>")

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
            print("⚠️ OCR 沒有辨識出任何文字")
            return []
            
        # 台灣股票代碼通常為 4 位數字，有時 5-6 位 (權證/ETF)
        # 放寬正則表達式，不強制要求雙向邊界，但要求字串中包含 4-6 位數字
        symbol_pattern = re.compile(r'(\d{4,6})')
        found_stocks = {}
        
        # 過濾清單：常見的表格標題文字，避免被誤認為股票名稱
        filter_list = ["股票名稱", "代碼", "現價", "帳面", "獲利", "成本", "現現", "現現股", "現資", "資資", "資現", "幣別", "資產"]

        for i, item in enumerate(data):
            text = item['text']
            match = symbol_pattern.search(text)
            
            if match:
                symbol = match.group(1)
                
                # 如果該字串本身就是 4-6 位數字，或是帶有一些雜訊的代碼
                if len(symbol) >= 4:
                    # 嘗試尋找名稱：通常在代碼的前後
                    name = ""
                    # 1. 檢查同一個文字塊中是否有中文字 (例如 "台積電2330")
                    if any('\u4e00' <= char <= '\u9fff' for char in text):
                         # 去掉數字部分，剩下的可能是名稱
                         name = re.sub(r'\d+', '', text).strip()
                    
                    # 2. 如果同塊沒有名稱，查看前後索引 (前後 2 個索引內)
                    if not name:
                        for offset in [-1, 1, -2, 2]:
                            idx = i + offset
                            if 0 <= idx < len(data):
                                candidate = data[idx]['text']
                                # 包含中文字且長度大於 1 且不在過濾清單中
                                if any('\u4e00' <= char <= '\u9fff' for char in candidate) and len(candidate) > 1:
                                    if not any(f in candidate for f in filter_list):
                                        name = candidate
                                        break
                    
                    # 清理名稱：移除一些已知的干擾字元，但保留權證名稱中的英數
                    # 只移除一些明顯的表格文字
                    for f in filter_list:
                        name = name.replace(f, "")
                    name = name.strip()
                    
                    if symbol not in found_stocks:
                        # 只有當名稱不是純數字或太短時才記錄，或者至少給個預設名
                        found_stocks[symbol] = name if name else "未知名稱"
        
        results = []
        for symbol, name in found_stocks.items():
            results.append({
                "symbol": symbol,
                "name": name
            })
            
        print(f"✅ OCR 分析完成，找到 {len(results)} 個標的")
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

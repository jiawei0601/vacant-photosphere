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
            # 使用 document_text_detection 處理密集的表格文字
            response = self.client.document_text_detection(image=image)
            full_text_obj = response.full_text_annotation

            if response.error.message:
                raise Exception(f"{response.error.message}")

            if not full_text_obj:
                return []

            extracted_text = []
            # 從全文結構中提取區塊，Google 會自動幫我們排好順序
            for page in full_text_obj.pages:
                for block in page.blocks:
                    for paragraph in block.paragraphs:
                        para_text = ""
                        for word in paragraph.words:
                            word_text = "".join([symbol.text for symbol in word.symbols])
                            para_text += word_text
                        
                        if para_text:
                            extracted_text.append({
                                "text": para_text.strip(),
                                "confidence": 1.0,
                                "bbox": [] # document 模式的 bbox 結構較複雜，暫不傳回
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
            
        # 台灣股票代碼：4-6 位數字，後方可能跟著一個大寫字母 (如 ETF 或權證)
        symbol_pattern = re.compile(r'(\d{4,6}[A-Z]?)')
        found_stocks = {}
        
        # 過濾清單：常見的表格標題文字
        filter_list = ["股票名稱", "代碼", "現價", "帳面", "獲利", "成本", "現現", "現現股", "現資", "資資", "資現", "幣別", "資產", "淨值", "獲利率", "現值"]

        for i, item in enumerate(data):
            text = item['text']
            match = symbol_pattern.search(text.upper())
            
            if match:
                symbol = match.group(1)
                
                if len(symbol) >= 4:
                    name = ""
                    # 1. 如果同文字塊有中文，優先從塊中提取
                    if any('\u4e00' <= char <= '\u9fff' for char in text):
                         # 僅移除代碼本身，保留其他字元（如權證名稱中的數字）
                         potential_name = text.replace(symbol, '').replace(symbol.lower(), '').strip()
                         if len(potential_name) > 1:
                             name = potential_name
                    
                    # 2. 前後尋找 (名稱通常在代碼的正上方或左邊塊)
                    if not name:
                        for offset in [-1, 1, -2, 2]:
                            idx = i + offset
                            if 0 <= idx < len(data):
                                candidate = data[idx]['text']
                                if any('\u4e00' <= char <= '\u9fff' for char in candidate) and len(candidate) > 1:
                                    if not any(f in candidate for f in filter_list):
                                        name = candidate
                                        break
                    
                    # 清理名稱：移除過濾字與兩端雜訊
                    for f in filter_list:
                        name = name.replace(f, "")
                    # 移除首尾可能的括號或特殊符號
                    name = re.sub(r'^[\(\)\s\-\.]+|[\(\)\s\-\.]+$', '', name)
                    
                    if symbol not in found_stocks:
                        found_stocks[symbol] = name if name else "未知名稱"
        
        results = []
        for symbol, name in found_stocks.items():
            results.append({
                "symbol": symbol,
                "name": name
            })
            
        print(f"✅ OCR 分析完成，找到 {len(results)} 個標的: {[r['symbol'] for r in results]}")
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

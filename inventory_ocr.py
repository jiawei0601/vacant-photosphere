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
        處理圖片並提取文字區塊及其座標
        """
        if not self.client:
            return []

        try:
            with io.open(image_path, 'rb') as image_file:
                content = image_file.read()

            image = vision.Image(content=content)
            response = self.client.document_text_detection(image=image)
            full_text_obj = response.full_text_annotation

            if response.error.message or not full_text_obj:
                return []

            extracted_items = []
            for page in full_text_obj.pages:
                for block in page.blocks:
                    for paragraph in block.paragraphs:
                        # 獲取段落中心點 Y 座標作為排序基準
                        vertices = paragraph.bounding_box.vertices
                        y_coords = [v.y for v in vertices]
                        center_y = sum(y_coords) / len(y_coords)
                        
                        # 獲取段落中心點 X 座標
                        x_coords = [v.x for v in vertices]
                        center_x = sum(x_coords) / len(x_coords)

                        para_text = "".join(["".join([s.text for s in w.symbols]) for w in paragraph.words])
                        
                        if para_text:
                            extracted_items.append({
                                "text": para_text.strip(),
                                "x": center_x,
                                "y": center_y
                            })

            return extracted_items
        except Exception as e:
            print(f"Vision API Error: {e}")
            return []

    def extract_stock_info(self, image_path):
        """
        利用座標分組技術精準提取表格資料
        """
        items = self.process_image(image_path)
        if not items:
            return []

        # 1. 根據 Y 座標分組 (允許 15 像素以內的誤差視為同一行)
        items.sort(key=lambda i: i['y'])
        rows = []
        if items:
            current_row = [items[0]]
            for i in range(1, len(items)):
                if abs(items[i]['y'] - current_row[-1]['y']) < 20: # 稍微放寬行距
                    current_row.append(items[i])
                else:
                    rows.append(sorted(current_row, key=lambda r: r['x']))
                    current_row = [items[i]]
            rows.append(sorted(current_row, key=lambda r: r['x']))

        # 2. 遍歷每一行提取數據
        results = []
        symbol_pattern = re.compile(r'(\d{4,6}[A-Z]?)')
        
        for row in rows:
            row_text_list = [item['text'] for item in row]
            full_row_str = "|".join(row_text_list)
            
            # 尋找代碼
            match = symbol_pattern.search(full_row_str.upper())
            if match:
                symbol = match.group(1)
                
                # 尋找名稱 (通常在代碼附近的文字塊)
                name = "未知名稱"
                for i, item in enumerate(row):
                    if symbol in item['text'].upper():
                        # 如果同塊有中文
                        if any('\u4e00' <= char <= '\u9fff' for char in item['text']):
                            name = item['text'].replace(symbol, '').replace(symbol.lower(), '').strip()
                        # 或者是前一塊
                        elif i > 0 and any('\u4e00' <= char <= '\u9fff' for char in row[i-1]['text']):
                            name = row[i-1]['text']
                        break
                
                # 清理名稱
                name = re.sub(r'[^\u4e00-\u9fff\d\w]', '', name).strip()

                # --- 提取數值數據 ---
                quantity = 0
                avg_price = 0.0
                profit = 0
                
                # 建立一個包含所有純數字或帶逗號數字的列表 (依 X 座標排序)
                numbers = []
                for item in row:
                    raw = item['text'].replace(',', '')
                    # 處理帶正負號或小數點的數字
                    try:
                        clean_num = re.sub(r'[^-0-9.]', '', raw)
                        if clean_num and clean_num not in [symbol, ""]:
                            numbers.append(float(clean_num))
                    except:
                        continue

                # 根據台股常見券商表格版面推算：
                # 截圖順序: [代碼] .. [庫存] .. [損益] .. [均價]
                # 注意：這只是試探性邏輯，可以根據您的截圖微調
                if len(numbers) >= 3:
                     # 通常較大的整數是庫存，帶小數的是均價，損益可能有正負
                     # 我們根據位置推測：
                     # [即時庫存] 通常出現在代碼後方的第 1~2 個數字
                     quantity = int(numbers[0]) if numbers[0] == int(numbers[0]) else 0
                     
                     # [損益] 搜尋包含正負號或較大數值的
                     for n in numbers:
                         if abs(n) > 50 and n == int(n): # 損益通常是較大整數
                             profit = int(n)
                             break
                     
                     # [均價] 通常是較小的、帶有小數點的
                     for n in numbers:
                         if 0 < n < 10000 and n != quantity:
                             avg_price = n # 暫取最後一個符合條件的
                
                results.append({
                    "symbol": symbol,
                    "name": name if name else "未知名稱",
                    "quantity": quantity,
                    "avg_price": avg_price,
                    "profit": profit
                })

        print(f"✅ OCR Row-Analysis Done. Found {len(results)} items.")
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

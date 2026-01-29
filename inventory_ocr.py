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
        """
        self.usage_file = "vision_usage.json"
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

    def _get_usage(self):
        """讀取本月使用量"""
        from datetime import datetime
        month_key = datetime.now().strftime("%Y-%m")
        if os.path.exists(self.usage_file):
            try:
                with open(self.usage_file, 'r') as f:
                    data = json.load(f)
                    if data.get("month") == month_key:
                        return data.get("count", 0)
            except:
                pass
        return 0

    def _increment_usage(self):
        """增加使用量計數"""
        from datetime import datetime
        month_key = datetime.now().strftime("%Y-%m")
        current_count = self._get_usage() + 1
        with open(self.usage_file, 'w') as f:
            json.dump({"month": month_key, "count": current_count}, f)
        return current_count

    def get_monthly_usage_report(self):
        """獲取使用量報告字串"""
        count = self._get_usage()
        # Google Vision 免費額度為 1,000 次/月
        free_limit = 1000
        remaining = max(0, free_limit - count)
        return (
            f"📊 **Vision API 本月使用量**\n"
            f"• 本次辨識後累計: `{count}` 次\n"
            f"• 剩餘免費額度: `{remaining}` 次\n"
            f"(註: 此計數在重新部署時會歸零)"
        )

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

            # 增加使用量計數
            self._increment_usage()

            if response.error.message or not full_text_obj:
                return []

            extracted_items = []
            for page in full_text_obj.pages:
                for block in page.blocks:
                    for paragraph in block.paragraphs:
                        # 獲取中心點座標
                        vertices = paragraph.bounding_box.vertices
                        center_y = sum([v.y for v in vertices]) / len(vertices)
                        center_x = sum([v.x for v in vertices]) / len(vertices)

                        # 改進：文字塊之間必須保留空格，避免數字粘連
                        words_text = []
                        for word in paragraph.words:
                            word_str = "".join([s.text for s in word.symbols])
                            words_text.append(word_str)
                        
                        para_text = " ".join(words_text)
                        
                        if para_text.strip():
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
        精準提取表格各欄位數據
        """
        items = self.process_image(image_path)
        if not items:
            return []

        # 1. 根據 Y 座標分組
        items.sort(key=lambda i: i['y'])
        rows = []
        if items:
            current_row = [items[0]]
            for i in range(1, len(items)):
                if abs(items[i]['y'] - current_row[-1]['y']) < 25: 
                    current_row.append(items[i])
                else:
                    rows.append(sorted(current_row, key=lambda r: r['x']))
                    current_row = [items[i]]
            rows.append(sorted(current_row, key=lambda r: r['x']))

        results = []
        # 精確匹配 4 位數字股票或 6 位數字權證
        symbol_pattern = re.compile(r'\b(\d{4}|\d{6})\b')
        
        for row in rows:
            row_str = " ".join([it['text'] for it in row]).upper()
            # 找到所有可能的代碼候選
            symbols = symbol_pattern.findall(row_str)
            if not symbols: continue

            # 優先取 6 位 (權證)，其次取 4 位，且排除掉明顯是時間或長流水號的片段
            symbol = ""
            for s in symbols:
                if len(s) == 6 or len(s) == 4:
                    symbol = s
                    break
            if not symbol: continue

            # 找到代碼所在的 Item 及其索引
            s_idx = -1
            s_item = None
            for i, it in enumerate(row):
                if symbol in it['text'].upper():
                    s_idx = i
                    s_item = it
                    break
            
            if s_idx == -1: continue

            # 提取名稱：略過交易類型字詞，且只看代碼左側或同塊
            raw_name = ""
            for it in row:
                if it['x'] <= s_item['x'] + 10: # 包含代碼同塊
                    txt = it['text'].replace(symbol, '').strip()
                    # 移除純數字或常見類別字
                    txt = re.sub(r'^(現股|融資|融券|代銷|資|券)$', '', txt)
                    if any('\u4e00' <= char <= '\u9fff' for char in txt):
                        raw_name += txt
            
            # 清理名稱：移除掉尾部可能殘留的數字（通常是權證名稱自帶的數字，不是數據）
            name = re.sub(r'(現股|融資|融券|代銷)', '', raw_name).strip()

            # --- 關鍵：提取純數字數據，嚴格限制在代碼右側 ---
            data_numbers = []
            for it in row:
                # 僅處理位於代碼右側的數字塊，避免抓到名稱裡的數字 (如 56購01)
                if it['x'] > s_item['x'] - 5:
                    txt = it['text'].upper().replace(',', '').strip()
                    
                    # 處理代碼粘連
                    if symbol in txt and len(txt) > len(symbol):
                        parts = txt.split(symbol)
                        for p in parts:
                            if p:
                                nums = re.findall(r'-?\d+\.?\d*', p)
                                for n in nums:
                                    try: data_numbers.append(float(n))
                                    except: continue
                    else:
                        # 正常數字塊
                        nums = re.findall(r'-?\d+\.?\d*', txt)
                        for n in nums:
                            try:
                                # 排除掉純代碼
                                if n == float(symbol) and len(txt) == len(symbol):
                                    continue
                                data_numbers.append(float(n))
                            except: continue

            quantity = 0
            avg_price = 0.0
            profit = 0

            # 針對代碼右側的數字進行精準分配
            if len(data_numbers) >= 1:
                # 1. 數量：取右側第一個整數
                for n in data_numbers:
                    if n == int(n) and n > 0:
                        quantity = int(n)
                        break
                
                # 2. 均價：取帶有小數或合理的價格區間
                for n in reversed(data_numbers):
                    if 0 < n < 5000 and n != quantity:
                        # 優先取有小數點的
                        if n != int(n) or avg_price == 0:
                            avg_price = n
                            if n != int(n): break 

                # 3. 損益：取整行最後一個整數 (損益通常在最右邊)
                for n in reversed(data_numbers):
                    if n == int(n) and n != quantity:
                        profit = int(n)
                        break

            results.append({
                "symbol": symbol,
                "name": name if name else "未知標的",
                "quantity": abs(quantity),
                "avg_price": avg_price,
                "profit": profit
            })

        print(f"✅ OCR 精準分析完成，找到 {len(results)} 個標的。")
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

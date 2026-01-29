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
            for i, it in enumerate(row):
                if symbol in it['text'].upper():
                    s_idx = i
                    break
            
            if s_idx == -1: continue

            # 提取名稱：略過交易類型字詞 (如 現股, 融資, 融券)
            raw_name = ""
            # 優先找代碼前面的區塊
            search_items = row[:s_idx+1]
            for it in reversed(search_items):
                txt = it['text']
                # 過濾掉代碼本身與常見動作字
                txt = txt.replace(symbol, '').strip()
                clean_txt = re.sub(r'[^\u4e00-\u9fff\d\w]', '', txt)
                # 略過純類別字
                if clean_txt in ["現股", "融資", "融券", "代銷", "資", "券"]:
                    continue
                if any('\u4e00' <= char <= '\u9fff' for char in clean_txt):
                    raw_name = clean_txt
                    break
            
            name = re.sub(r'(現股|融資|融券|代銷)', '', raw_name).strip()

            # --- 關鍵：提取純數字數據，處理「粘連」問題 ---
            data_numbers = []
            for it in row[s_idx:]:
                txt = it['text'].upper().replace(',', '').strip()
                
                # 如果這個區塊包含了代碼，且長度明顯過長，嘗試拆分
                if symbol in txt and len(txt) > len(symbol):
                    # 範例: "5502043316" (55 + 020433 + 16)
                    parts = txt.split(symbol)
                    for p in parts:
                        if p: # 這裡 p 可能是 "55" 或 "16"
                            nums = re.findall(r'-?\d+\.?\d*', p)
                            for n in nums:
                                try: data_numbers.append(float(n))
                                except: continue
                    # 同時也要把 symbol 附近可能跟它粘在一起的數字算進去，但通常我們只需要 symbol 兩側的
                else:
                    # 正常的純數字或不含 symbol 的區塊
                    nums = re.findall(r'-?\d+\.?\d*', txt)
                    for n in nums:
                        try:
                            # 排除掉剛好等於代碼的純數字塊，避免重複計算
                            if n == symbol and len(txt) == len(symbol):
                                continue
                            data_numbers.append(float(n))
                        except: continue

            quantity = 0
            avg_price = 0.0
            profit = 0

            # 針對拆分後的數字進行欄位分配
            if len(data_numbers) >= 1:
                # 1. 數量：通常是整行中第一個出現的數字 (或在代碼左側/粘連左側)
                quantity = int(data_numbers[0])
                
                # 2. 損益：尋找之後出現的較大整數
                if len(data_numbers) >= 2:
                    for n in data_numbers[1:]:
                        if n == int(n) and abs(n) > 1:
                            profit = int(n)
                            break
                            
                # 3. 均價：從最後面往前找合理的價格
                for n in reversed(data_numbers):
                    if 0 < n < 5000:
                        if n != quantity:
                            avg_price = n
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

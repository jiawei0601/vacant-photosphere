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
            
            # 清理名稱：移除掉開頭與尾部可能殘留的數字與雜質
            name = re.sub(r'^[|\[【\s]*', '', raw_name) # 移除左側符號
            name = re.sub(r'(現股|現 股|融資|融券|代銷)', '', name).strip()
            name = name.lstrip('|').lstrip('【').strip()

            # --- 超強力提取純數字數據 ---
            data_numbers = []
            for it in row:
                # 嚴格限制在代碼右側或同塊中代碼之後的內容
                if it['x'] > s_item['x'] - 2:
                    txt = it['text'].upper().replace(',', '').strip()
                    # 移除代碼干擾
                    if symbol in txt:
                        parts = txt.split(symbol)
                        text_to_scan = " ".join(parts)
                    else:
                        text_to_scan = txt
                        
                    # 尋找所有數字 (含負號)
                    nums = re.findall(r'-?\d+\.?\d*', text_to_scan)
                    for n in nums:
                        try:
                            f_n = float(n)
                            # 排除純代碼
                            if f_n == float(symbol) and len(n) == len(symbol):
                                continue
                            data_numbers.append(f_n)
                        except: continue

            quantity = 0
            avg_price = 0.0
            profit = 0

            # 針對收集到的數字列表 [已排序] 進行智慧分配
            if len(data_numbers) >= 2:
                # 1. 損益：通常在最右邊 (最後一個數字)
                # 如果最後一個是整數，高度機率是損益
                if data_numbers[-1] == int(data_numbers[-1]):
                    profit = int(data_numbers[-1])
                    remaining_nums = data_numbers[:-1]
                else:
                    # 如果最後一個不是整數(可能是均價)，損益在倒數第二個
                    profit = int(data_numbers[-2]) if len(data_numbers) > 2 else 0
                    remaining_nums = data_numbers[:-2]

                # 2. 數量：在剩下的數字中，第一個整數通常是數量
                for n in remaining_nums:
                    if n == int(n) and n > 0:
                        quantity = int(n)
                        # 特殊修正：如果數量跟代碼一樣且後面還有數字，再往下找
                        if quantity == float(symbol) and len(remaining_nums) > 1:
                            continue
                        break
                
                # 3. 均價：剩餘數字中，最像價格的 (有小數或在 quantity 附近的)
                for n in remaining_nums:
                    if (n != quantity) and 0 < n < 5000:
                        avg_price = n
                        if n != int(n): break # 優先選帶小數的

            # 特殊邏輯：針對只有兩個數字的情況 (數量 + 損益)
            elif len(data_numbers) == 1:
                quantity = int(data_numbers[0])

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

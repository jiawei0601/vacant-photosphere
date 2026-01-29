import io
import cv2
import numpy as np
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
                        v_list = [{"x": v.x, "y": v.y} for v in vertices]
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
                                "y": center_y,
                                "vertices": v_list
                            })

            return extracted_items
        except Exception as e:
            print(f"Vision API Error: {e}")
            return []

    def _get_color_sign(self, cv_img, vertices):
        """
        分析塊的顏色：紅色為正(1)，綠色為負(-1)，其餘為中性(0)
        """
        if cv_img is None: return 0
        try:
            min_x = int(min([v['x'] for v in vertices]))
            max_x = int(max([v['x'] for v in vertices]))
            min_y = int(min([v['y'] for v in vertices]))
            max_y = int(max([v['y'] for v in vertices]))
            
            h, w = cv_img.shape[:2]
            p = 1 # 邊距
            roi = cv_img[max(0, min_y-p):min(h, max_y+p), max(0, min_x-p):min(w, max_x+p)]
            if roi.size == 0: return 0
            
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            # 紅色範圍
            lower_red1, upper_red1 = np.array([0, 50, 50]), np.array([10, 255, 255])
            lower_red2, upper_red2 = np.array([160, 50, 50]), np.array([180, 255, 255])
            # 綠色範圍 (調廣一點以抓到深綠)
            lower_green, upper_green = np.array([35, 40, 40]), np.array([90, 255, 255])
            
            mask_r = cv2.bitwise_or(cv2.inRange(hsv, lower_red1, upper_red1), cv2.inRange(hsv, lower_red2, upper_red2))
            mask_g = cv2.inRange(hsv, lower_green, upper_green)
            
            r_pixels = cv2.countNonZero(mask_r)
            g_pixels = cv2.countNonZero(mask_g)
            
            if r_pixels > g_pixels and r_pixels > 5: return 1
            if g_pixels > r_pixels and g_pixels > 5: return -1
        except: pass
        return 0

    def extract_stock_info(self, image_path):
        """
        精準提取表格各欄位數據
        """
        items = self.process_image(image_path)
        if not items:
            return []
        
        # 讀取圖片用於顏色分析
        cv_img = cv2.imread(image_path)

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
            data_candidates = []
            for it in row:
                if it['x'] > s_item['x'] - 5:
                    txt = it['text'].upper().replace(',', '').strip()
                    if symbol in txt:
                        scan_text = txt.split(symbol, 1)[-1]
                    else:
                        scan_text = txt
                        
                    raw_nums = re.findall(r'-?\d+\.?\d*', scan_text)
                    for n in raw_nums:
                        try:
                            f_n = float(n)
                            if f_n == float(symbol) and len(n) == len(symbol):
                                continue
                            # 獲取該數字的顏色屬性
                            c_sign = self._get_color_sign(cv_img, it.get('vertices', []))
                            data_candidates.append({"val": f_n, "color": c_sign})
                        except: continue

            quantity = 0
            avg_price = 0.0
            profit = 0

            if len(data_candidates) >= 2:
                # 1. 損益：通常在最右邊
                c_profit = data_candidates[-1]
                if c_profit['val'] == int(c_profit['val']) or len(data_candidates) == 2:
                    profit = int(c_profit['val'])
                    # 顏色套用點：損益欄位
                    if c_profit['color'] == -1: profit = -abs(profit)
                    if c_profit['color'] == 1: profit = abs(profit)
                    rem_candidates = data_candidates[:-1]
                else:
                    c_profit = data_candidates[-2]
                    profit = int(c_profit['val'])
                    if c_profit['color'] == -1: profit = -abs(profit)
                    if c_profit['color'] == 1: profit = abs(profit)
                    rem_candidates = data_candidates[:-2]

                # 2. 數量
                for c in rem_candidates:
                    n = c['val']
                    if n == int(n) and n > 0:
                        if n == float(symbol) and len(rem_candidates) > 1:
                            continue
                        quantity = int(n)
                        break
                
                # 3. 均價
                for c in data_candidates:
                    n = c['val']
                    if n != quantity and abs(n - profit) > 0.01 and 0 < n < 10000:
                        avg_price = n
                        if n != int(n): break

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

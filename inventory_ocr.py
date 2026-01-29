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
        使用精準座標定位方式進行 OCR 辨識
        """
        import re
        items = self.process_image(image_path)
        if not items:
            return []
        
        cv_img = cv2.imread(image_path)
        
        # 1. 根據 Y 座標將資料分行 (容許 15 像素誤差)
        items.sort(key=lambda i: i['y'])
        rows = []
        if items:
            current_row = [items[0]]
            for i in range(1, len(items)):
                if abs(items[i]['y'] - current_row[0]['y']) < 15:
                    current_row.append(items[i])
                else:
                    rows.append(sorted(current_row, key=lambda r: r['x']))
                    current_row = [items[i]]
            rows.append(sorted(current_row, key=lambda r: r['x']))

        # 2. 偵測表頭 X 座標定位點 (Anchor)
        anchors = {
            "symbol": None,
            "quantity": None,
            "profit": None,
            "price": None
        }
        
        # 遍歷前幾行尋找表頭
        for row in rows[:5]:
            for it in row:
                txt = it['text']
                if "代碼" in txt or "名稱" in txt: anchors["symbol"] = it['x']
                if "即時庫存" in txt or "庫存" in txt: anchors["quantity"] = it['x']
                if "損益" in txt: anchors["profit"] = it['x']
                if "付出成本" in txt or "成本均價" in txt or "均價" in txt: anchors["price"] = it['x']

        # 如果沒找到表頭，設定預設權重位置 (根據常見比例)
        print(f"📍 偵測到表頭定位: {anchors}")

        results = []
        symbol_pattern = re.compile(r'\b(\d{4}|\d{6})\b')

        for row in rows:
            row_str = " ".join([it['text'] for it in row]).upper()
            symbols = symbol_pattern.findall(row_str)
            if not symbols: continue
            
            # 找到代碼與其 Item
            symbol = symbols[0] # 取第一個找到的
            s_item = next((it for it in row if symbol in it['text']), None)
            if not s_item: continue

            # 提取名稱：尋找代碼左側或鄰近的中文塊
            name = ""
            for it in row:
                if it['x'] < s_item['x'] + 50: # 代碼左側或同塊
                    txt = re.sub(r'(現股|現\s?股|融資|融券|代銷|[0-9])', '', it['text'])
                    txt = re.sub(r'[^\u4e00-\u9fff]', '', txt)
                    if txt: name += txt
            
            # --- 投影定位取值 ---
            # 我們將行內所有數字及其 X 座標拿出來
            val_candidates = []
            for it in row:
                # 尋找數字塊
                nums = re.findall(r'-?\d+\.?\d*', it['text'].replace(',', ''))
                for n in nums:
                    try:
                        f_v = float(n)
                        if f_v == float(symbol) and len(n) == len(symbol): continue
                        val_candidates.append({
                            "val": f_v,
                            "x": it['x'],
                            "vertices": it.get('vertices', [])
                        })
                    except: continue

            quantity = 0
            profit = 0
            avg_price = 0.0

            # 根據與 Anchor 的距離分配數值
            if anchors["quantity"] is not None:
                match = min(val_candidates, key=lambda c: abs(c['x'] - anchors["quantity"]), default=None)
                if match: quantity = int(match['val'])

            if anchors["profit"] is not None:
                match = min(val_candidates, key=lambda c: abs(c['x'] - anchors["profit"]), default=None)
                if match: 
                    profit = int(match['val'])
                    # 色彩修正
                    c_sign = self._get_color_sign(cv_img, match['vertices'])
                    if c_sign == -1: profit = -abs(profit)
                    if c_sign == 1: profit = abs(profit)

            if anchors["price"] is not None:
                match = min(val_candidates, key=lambda c: abs(c['x'] - anchors["price"]), default=None)
                if match: avg_price = match['val']

            # 備援邏輯：如果沒表頭或沒勾到，用舊的排序邏輯 (略)
            if not quantity and val_candidates:
                 quantity = int(val_candidates[0]['val'])

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

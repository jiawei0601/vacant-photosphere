import os
import requests
import base64
import re
from dotenv import load_dotenv

load_dotenv()

class GoogleVisionOCR:
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_VISION_API_KEY")
        self.endpoint = f"https://vision.googleapis.com/v1/images:annotate?key={self.api_key}"

    def process_image(self, image_path):
        """
        將圖片傳送到 Google Cloud Vision 進行辨識
        """
        if not self.api_key:
            print("錯誤: 未設定 GOOGLE_VISION_API_KEY")
            return []

        try:
            with open(image_path, "rb") as image_file:
                content = base64.b64encode(image_file.read()).decode("utf-8")

            payload = {
                "requests": [
                    {
                        "image": {"content": content},
                        "features": [{"type": "TEXT_DETECTION"}]
                    }
                ]
            }

            response = requests.post(self.endpoint, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()

            # 提取文字結果
            annotations = data["responses"][0].get("textAnnotations", [])
            if not annotations:
                return []

            # annotations[0] 是整張圖的全文，後續是單個區塊
            extracted_text = []
            for entry in annotations[1:]:
                text = entry.get("description", "")
                vertices = entry.get("boundingPoly", {}).get("vertices", [])
                
                # 轉換為 bbox 格式 [[x,y], [x,y], [x,y], [x,y]]
                bbox = [[v.get("x", 0), v.get("y", 0)] for v in vertices]
                
                extracted_text.append({
                    "text": text,
                    "bbox": bbox
                })

            return extracted_text
        except Exception as e:
            print(f"Google Vision API 請求失敗: {e}")
            return []

    def get_monthly_usage_report(self):
        """回傳 OCR 使用量摘要"""
        return "📊 **OCR 使用量**\n• 平台: Google Cloud Vision\n• 免費額度: 1,000 次/月\n• 狀態: 正常運行中"

    def extract_stock_info(self, image_path):
        """
        解析 OCR 結果並提取股票資訊
        """
        data = self.process_image(image_path)
        if not data:
            return []

        # 1. 根據 y 軸坐標將文字分組為「行」
        rows = []
        for item in data:
            bbox = item['bbox']
            center_y = sum(p[1] for p in bbox) / 4
            
            found = False
            for row in rows:
                if abs(row['avg_y'] - center_y) < 15:
                    row['items'].append(item)
                    row['avg_y'] = sum(sum(p[1] for p in it['bbox']) / 4 for it in row['items']) / len(row['items'])
                    found = True
                    break
            if not found:
                rows.append({'avg_y': center_y, 'items': [item]})
        
        for row in rows:
            row['items'].sort(key=lambda x: x['bbox'][0][0])
        rows.sort(key=lambda x: x['avg_y'])

        results = []
        symbol_pattern = re.compile(r'\b\d{4,6}\b')
        num_pattern = re.compile(r'[+-]?[\d,]+(\.\d+)?')

        for row in rows:
            row_full_text = " ".join([item['text'] for item in row['items']])
            match = symbol_pattern.search(row_full_text)
            if not match: continue
            
            symbol = match.group()
            name = ""
            for item in row['items']:
                t = item['text']
                if any('\u4e00' <= char <= '\u9fff' for char in t):
                    name = re.sub(r'[^\u4e00-\u9fff-]', '', t)
                    if name: break

            numeric_values = []
            for item in row['items']:
                t = item['text'].replace(',', '')
                if num_pattern.fullmatch(t):
                    try:
                        numeric_values.append(float(t))
                    except: pass
            
            quantity, cost, profit = 0, 0.0, 0.0
            if len(numeric_values) >= 3:
                quantity = numeric_values[0]
                profit = numeric_values[2]
                if len(numeric_values) >= 7:
                    cost = numeric_values[7]
                else:
                    cost = numeric_values[-2] if len(numeric_values) >= 2 else 0

            results.append({
                "symbol": symbol,
                "name": name if name else "未知名稱",
                "quantity": quantity,
                "avg_price": cost,
                "profit": profit
            })
            
        return results

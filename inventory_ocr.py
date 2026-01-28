import easyocr
import re
import os
import cv2
import numpy as np

class InventoryOCR:
    def __init__(self, languages=['ch_tra', 'en']):
        """
        初始化 OCR 讀取器
        ch_tra: 繁體中文
        en: 英文
        """
        model_path = os.getenv("EASYOCR_MODULE_PATH", None)
        print(f"正在初始化 OCR 引擎 (模型路徑: {model_path or '預設'})...")
        self.reader = easyocr.Reader(languages, model_storage_directory=model_path)

    def process_image(self, image_path):
        """
        處理圖片並提取文字
        """
        if not os.path.exists(image_path):
            print(f"找不到圖片: {image_path}")
            return []

        print(f"正在解析圖片: {image_path}")
        results = self.reader.readtext(image_path)
        
        # 格式化結果: [(bbox, text, confidence), ...]
        extracted_text = []
        for (bbox, text, prob) in results:
            if prob > 0.3:  # 信心職過濾
                extracted_text.append({
                    "text": text.strip(),
                    "confidence": prob,
                    "bbox": bbox
                })
        
        return extracted_text

    def extract_stock_info(self, image_path):
        """
        從文字中分析股票代碼與可能的資訊
        """
        data = self.process_image(image_path)
        all_text = [item['text'] for item in data]
        
        # 台灣股票代碼通常為 4 位數字，有時 5-6 位
        # 我們主要尋找 4 位數字且周圍可能有中文字的模式
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

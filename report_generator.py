import os
from PIL import Image, ImageDraw, ImageFont
import pandas as pd
from datetime import datetime

class ReportGenerator:
    def __init__(self):
        self.bg_color = "#121212"
        self.card_color = "#1E1E1E"
        self.text_color = "#FFFFFF"
        self.up_color = "#FF4B4B"  # Red for Up (Taiwan style)
        self.down_color = "#00FA9A" # Green for Down (Taiwan style)
        self.accent_color = "#00D1FF"
        
        # Try to find a font that supports Chinese. 
        self.font_path = None
        
        # 優先順序: 1. 專案路徑下的字體 2. 系統字體
        potential_fonts = [
            # 專案本地字體 (建議使用者上傳一個字體到此路徑以確保不同環境一致)
            "assets/fonts/msjh.ttc",
            "assets/fonts/NotoSansTC-Regular.otf",
            "assets/fonts/font.ttc",
            "assets/fonts/font.ttf",
            
            # Windows 字體
            "C:/Windows/Fonts/msjh.ttc",  # Microsoft JhengHei
            "C:/Windows/Fonts/msjh.ttf",
            "C:/Windows/Fonts/msjhl.ttc",
            "C:/Windows/Fonts/mingliu.ttc",
            
            # Linux (Railway) 常用字體路徑
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallback.ttf",
            "/usr/share/fonts/truetype/arphic/uming.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        ]
        
        for f in potential_fonts:
            # 檢查絕對路徑或相對路徑
            target = f if os.path.isabs(f) else os.path.join(os.getcwd(), f)
            if os.path.exists(target):
                self.font_path = target
                print(f"✅ 已找到字體庫: {self.font_path}")
                break
        
        if not self.font_path:
            print("⚠️ 警告: 系統找不到中文字體，圖片中的中文將顯示為亂碼。")
            print("💡 建議: 請下載一個支援中文的字體檔 (如 NotoSansTC-Regular.otf) 並放至 assets/fonts/ 資料夾下。")

    def generate_closing_report(self, sentiment_data, stock_list, output_path="closing_report.png"):
        """
        sentiment_data: {date, sentiment, diff_vol, overheat_index}
        stock_list: list of {name, symbol, close, change_pct, ma20_status}
        """
        # Canvas size - dynamic height
        row_height = 100
        header_height = 550
        canvas_height = max(1100, header_height + (len(stock_list) * row_height) + 120)
        
        width = 1200
        img = Image.new('RGB', (width, canvas_height), color=self.bg_color)
        draw = ImageDraw.Draw(img)
        
        # Load fonts - Further Increased sizes
        try:
            title_font = ImageFont.truetype(self.font_path, 72) if self.font_path else ImageFont.load_default()
            subtitle_font = ImageFont.truetype(self.font_path, 42) if self.font_path else ImageFont.load_default()
            body_font = ImageFont.truetype(self.font_path, 36) if self.font_path else ImageFont.load_default()
            small_font = ImageFont.truetype(self.font_path, 28) if self.font_path else ImageFont.load_default()
        except:
            title_font = subtitle_font = body_font = small_font = ImageFont.load_default()

        # Header
        draw.text((40, 40), f"台股每日盤後綜合報告", font=title_font, fill=self.accent_color)
        draw.text((40, 100), f"日期: {sentiment_data.get('date', '---')} | 生成時間: {datetime.now().strftime('%H:%M')}", font=small_font, fill="#AAAAAA")
        
        # --- Market Sentiment Card ---
        draw.rounded_rectangle([40, 150, 960, 400], radius=15, fill=self.card_color)
        draw.text((70, 180), "市場氣氛與買賣力道", font=subtitle_font, fill=self.text_color)
        
        if not sentiment_data:
            sentiment_data = {"date": "---", "sentiment": "---", "diff_vol": 0, "overheat_index": 0}
        
        # Sentiment Info
        sent = sentiment_data.get('sentiment', '---')
        overheat = sentiment_data.get('overheat_index', 0)
        diff_vol = sentiment_data.get('diff_vol', 0)
        
        sent_color = self.up_color if "多" in sent else self.down_color if "空" in sent else self.text_color
        
        draw.text((70, 240), f"市場氣分: {sent}", font=body_font, fill=sent_color)
        draw.text((70, 280), f"買賣量差: {diff_vol:+,}", font=body_font, fill=self.text_color)
        draw.text((70, 320), f"過熱指數: {overheat:.2f}%", font=body_font, fill=self.accent_color)
        
        # --- Stock List Title ---
        list_start_y = 430
        draw.text((40, list_start_y), "監控標的盤後統計", font=subtitle_font, fill=self.text_color)
        
        # Table Header
        header_y = list_start_y + 80
        draw.text((60, header_y), "股票名稱", font=body_font, fill="#AAAAAA")
        draw.text((380, header_y), "收盤", font=body_font, fill="#AAAAAA")
        draw.text((550, header_y), "漲跌", font=body_font, fill="#AAAAAA")
        draw.text((750, header_y), "MA20 狀態", font=body_font, fill="#AAAAAA")
        draw.text((1000, header_y), "成交量", font=body_font, fill="#AAAAAA")
        
        draw.line([60, header_y+60, width-60, header_y+60], fill="#333333", width=2)
        
        # Render Rows
        curr_y = header_y + 100
        for stock in stock_list:
            color = self.up_color if stock['change_pct'] > 0 else self.down_color if stock['change_pct'] < 0 else self.text_color
            
            # Name & Symbol
            draw.text((60, curr_y), f"{stock['name']}", font=body_font, fill=self.text_color)
            draw.text((60, curr_y+40), f"{stock['symbol']}", font=small_font, fill="#888888")
            
            # Price
            draw.text((380, curr_y), f"{stock['close']}", font=body_font, fill=self.text_color)
            
            # Change %
            change_str = f"{stock['change_pct']:+.2f}%" if stock['change_pct'] is not None else "---"
            draw.text((550, curr_y), change_str, font=body_font, fill=color)
            
            # MA Status
            ma_status = stock.get('ma20_status', '---')
            ma_color = self.up_color if "站上" in ma_status else self.down_color if "跌破" in ma_status else "#AAAAAA"
            draw.text((750, curr_y), ma_status, font=body_font, fill=ma_color)
            
            # Volume
            volume_str = f"{stock.get('volume', 0):,}"
            draw.text((1000, curr_y), volume_str, font=body_font, fill="#AAAAAA")
            
            curr_y += row_height
            draw.line([60, curr_y-20, width-60, curr_y-20], fill="#222222", width=1)
            
        # Footer
        draw.text((width//2 - 150, canvas_height - 60), "Antigravity Stock Monitor v2.1", font=small_font, fill="#555555")
        
        img.save(output_path)
        return output_path

if __name__ == "__main__":
    # Test
    gen = ReportGenerator()
    data = {"date": "2026-01-26", "sentiment": "🐂 偏多", "diff_vol": 123456, "overheat_index": 12.34}
    stocks = [
        {"name": "台積電", "symbol": "2330", "close": 580, "change_pct": 1.2, "ma20_status": "📈 站上 MA20"},
        {"name": "鴻海", "symbol": "2317", "close": 110, "change_pct": -0.5, "ma20_status": "📉 跌破 MA20"},
    ]
    gen.generate_closing_report(data, stocks, "test_report.png")
    print("Test report generated.")

import os
import time
import asyncio
from datetime import datetime, time as dt_time
from dotenv import load_dotenv

from price_fetcher import PriceFetcher
from notion_helper import NotionHelper
from notifier import Notifier

load_dotenv()

class MarketMonitor:
    def __init__(self):
        self.fetcher = PriceFetcher()
        self.notion = NotionHelper()
        self.notifier = Notifier()
        self.interval = int(os.getenv("CHECK_INTERVAL_SECONDS", 300))
        self.allow_outside = os.getenv("ALLOW_OUTSIDE_MARKET_HOURS", "false").lower() == "true"
        self.last_open_date = None
        self.last_close_date = None

    def is_market_open(self):
        """
        判斷台股是否在交易時段 (09:00 - 13:30)
        週一至週五
        """
        if self.allow_outside:
            return True
            
        now = datetime.now()
        # 0 為週一, 4 為週五
        if now.weekday() > 4:
            return False
            
        market_start = dt_time(9, 0)
        market_end = dt_time(13, 35) # 稍微多抓一點緩衝
        current_time = now.time()
        
        return market_start <= current_time <= market_end

    async def check_once(self):
        print(f"[{datetime.now()}] 開始執行價格檢查...")
        
        items = self.notion.get_monitoring_list()
        if not items:
            print("目前沒有要監控的標的。")
            return

        for item in items:
            symbol = item['symbol']
            price = self.fetcher.get_last_price(symbol)
            
            if price is None:
                continue
                
            print(f"處理 {item['name']} ({symbol}): 當前價格 {price}")
            
            status = "正常"
            alert_msg = ""
            
            # 檢查警戒值
            is_triggered = False
            if item['high_alert'] and price >= item['high_alert']:
                is_triggered = True
                status = "警戒"
                alert_msg = f"🔔 持續警報：[{item['name']} ({symbol})] 當前價格 {price} >= 上限 {item['high_alert']}\n(回覆 /stop {symbol} 停止警報)"
            elif item['low_alert'] and price <= item['low_alert']:
                is_triggered = True
                status = "警戒"
                alert_msg = f"🔔 持續警報：[{item['name']} ({symbol})] 當前價格 {price} <= 下限 {item['low_alert']}\n(回覆 /stop {symbol} 停止警報)"
            
            # 處理持續警報邏輯
            if is_triggered:
                # 只有當使用者還沒說 /stop 時才發送
                if not self.notifier.is_stopped(symbol):
                    await self.notifier.send_message(alert_msg)
                else:
                    print(f"{symbol} 處於警報範圍但已被使用者暫停。")
            else:
                # 如果價格回到正常範圍，自動從停止清單移除，以便下次觸發時能再次通知
                if self.notifier.is_stopped(symbol):
                    self.notifier.stopped_symbols.remove(symbol.upper())
                    print(f"{symbol} 價格已回歸正常，重設警報狀態。")
            
            # 更新 Notion
            self.notion.update_price_and_status(item['page_id'], price, status)

    async def get_summary_callback(self, offset=0):
        """回傳目前所有監控標的的摘要文字"""
        if offset > 0:
            return await self.get_detailed_summary(offset=offset)
            
        items = self.notion.get_monitoring_list()
        if not items:
            return ""
            
        lines = []
        for item in items:
            symbol = item['symbol']
            price = item.get('current_price', '---')
            status = item.get('status', '正常')
            
            # 格式化輸出
            line = f"• **{item['name']}** ({symbol})\n"
            line += f"  價: `{price}` | 限: `{item['low_alert']} ~ {item['high_alert']}`\n"
            line += f"  狀態: {status}{' (已暫停)' if self.notifier.is_stopped(symbol) else ''}"
            lines.append(line)
            
        return "\n\n".join(lines)

    async def change_alert_callback(self, symbol, high=None, low=None):
        """處理來自 Telegram 的警戒值修改請求"""
        # 重新獲取清單以尋找 page_id
        items = self.notion.get_monitoring_list()
        target = next((i for i in items if i['symbol'].upper() == symbol.upper()), None)
        
        if target:
            self.notion.update_alert_prices(target['page_id'], high_alert=high, low_alert=low)
            return True
        return False

    async def get_detailed_summary(self, offset=0):
        """回傳目前所有監控標的的詳細摘要 (開、收、高、低、MA20)"""
        items = self.notion.get_monitoring_list()
        if not items:
            return "目前監控清單為空。"
            
        lines = []
        date_info = ""
        for item in items:
            symbol = item['symbol']
            stats = self.fetcher.get_full_stats(symbol, offset=offset)
            
            if not stats:
                lines.append(f"• **{item['name']}** ({symbol}): 無法獲取詳細資料")
                continue
            
            if not date_info:
                date_info = f"📅 基準日期: `{stats['date']}`\n\n"
            
            # 漲跌幅顯示處理
            change_str = "---"
            if stats['change_pct'] is not None:
                emoji = "🔴" if stats['change_pct'] > 0 else "🟢" if stats['change_pct'] < 0 else "⚪"
                change_str = f"{emoji} {stats['change_pct']}%"
                
            line = f"• **{item['name']}** ({symbol})\n"
            line += f"  收: `{stats['close']}` ({change_str})\n"
            line += f"  開: `{stats['open']}` / 高: `{stats['high']}` / 低: `{stats['low']}`\n"
            line += f"  MA20: `{stats['ma20'] or '計算中'}`"
            lines.append(line)
            
        return date_info + "\n\n".join(lines)

    async def change_config_callback(self, interval=None, allow_outside=None):
        """處理來自 Telegram 的系統配置修改請求"""
        if interval is not None:
            self.interval = interval
            print(f"系統檢查間隔已更變為: {self.interval} 秒")
        
        if allow_outside is not None:
            self.allow_outside = allow_outside
            print(f"交易時段外處理已變更為: {self.allow_outside}")

    async def get_market_callback(self):
        """回傳市場指數資料"""
        return self.fetcher.get_market_indices()

    async def run_monitor_loop(self):
        """背景執行的監控迴圈"""
        while True:
            try:
                now = datetime.now()
                today = now.date()
                curr_time = now.time()
                is_weekday = now.weekday() <= 4

                # 處理開盤與收盤通知 (僅在非 24H 模式下強制執行，或作為每日常規提醒)
                if not self.allow_outside and is_weekday:
                    # 09:00 開盤提醒
                    if curr_time >= dt_time(9, 0) and curr_time < dt_time(9, 10):
                        if self.last_open_date != today:
                            # 獲取前一日摘要
                            prev_summary = await self.get_detailed_summary(offset=1)
                            message = f"☀️ **台股今日開盤**！\n\n📊 **前一交易日收盤報告**\n{prev_summary}\n\n系統已開始監控..."
                            await self.notifier.send_message(message)
                            self.last_open_date = today
                    
                    # 13:30 收盤總結
                    if curr_time >= dt_time(13, 30) and curr_time < dt_time(13, 50):
                        if self.last_close_date != today:
                            # 獲取詳細摘要
                            summary = await self.get_detailed_summary()
                            message = f"📉 **台股今日收盤總結**\n\n{summary}\n\n本日監控任務結束，明日再會！"
                            await self.notifier.send_message(message)
                            self.last_close_date = today

                if self.is_market_open():
                    await self.check_once()
                else:
                    print(f"[{datetime.now()}] 非交易時段，休眠中...")
            except Exception as e:
                print(f"監控迴圈發生錯誤: {e}")
            
            await asyncio.sleep(self.interval)

    def run(self):
        """啟動程式 (整合 Telegram run_polling)"""
        print("監控系統與 Telegram 機器人啟動中...")
        
        # 串接指令回呼
        self.notifier.set_data_callback(self.get_summary_callback)
        self.notifier.set_alert_callback(self.change_alert_callback)
        self.notifier.set_config_callback(self.change_config_callback)
        self.notifier.set_market_callback(self.get_market_callback)
        
        # 獲取 Telegram Application
        app = self.notifier.app
        if not app:
            print("無法獲取 Telegram Application，請檢查 Token。")
            return

        # 使用 post_init 來啟動背景監控任務
        async def post_init(application):
            asyncio.create_task(self.run_monitor_loop())
            print("背景監控任務已啟動。")

        # 啟動 Telegram 機器人 (這會阻塞並處理所有事件)
        app.post_init = post_init
        app.run_polling()

if __name__ == "__main__":
    monitor = MarketMonitor()
    monitor.run()

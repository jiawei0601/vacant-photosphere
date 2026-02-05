import os
import time
import asyncio
from datetime import datetime, time as dt_time, timezone, timedelta
from dotenv import load_dotenv

from price_fetcher import PriceFetcher
from notion_helper import NotionHelper
from notifier import Notifier
from report_generator import ReportGenerator

load_dotenv()

class MarketMonitor:
    def __init__(self):
        self.fetcher = PriceFetcher()
        self.notion = NotionHelper()
        self.notifier = Notifier()
        self.generator = ReportGenerator()
        self.interval = int(os.getenv("CHECK_INTERVAL_SECONDS", 600))
        self.allow_outside = os.getenv("ALLOW_OUTSIDE_MARKET_HOURS", "false").lower() == "true"
        self.last_open_date = None
        self.last_close_date = None
        self.last_noon_date = None
        self.last_daily_report_date = None
        self.last_check_time = 0
        self.taipei_tz = timezone(timedelta(hours=8))

    def _get_now_taipei(self):
        return datetime.now(self.taipei_tz)

    def is_market_open(self):
        if self.allow_outside: return True
        now = self._get_now_taipei()
        if now.weekday() > 4: return False
        market_start = dt_time(9, 0)
        market_end = dt_time(13, 35)
        return market_start <= now.time() <= market_end

    async def check_once(self, force=False):
        print(f"[{datetime.now()}] 執行價格檢查 (Fugle)...")
        items = self.notion.get_monitoring_list()
        if not items: return 0, 0

        success_count, fail_count = 0, 0
        for item in items:
            symbol = item['symbol']
            price_data = self.fetcher.get_last_price(symbol, force=force)
            if price_data is None:
                fail_count += 1
                continue
            
            price = price_data['price']
            fetch_time = price_data['time']
            is_cached = price_data.get('is_cached', False)
            success_count += 1
            
            status = "正常"
            is_triggered = False
            time_info = f"\n(資料時間: {fetch_time}{' 快取' if is_cached else ''})"
            
            if item['high_alert'] and price >= item['high_alert']:
                is_triggered, status = True, "警戒"
                alert_msg = f"🔔 上限警報：[{item['name']} ({symbol})] 價格 {price} >= {item['high_alert']}{time_info}"
            elif item['low_alert'] and price <= item['low_alert']:
                is_triggered, status = True, "警戒"
                alert_msg = f"🔔 下限警報：[{item['name']} ({symbol})] 價格 {price} <= {item['low_alert']}{time_info}"
            
            if is_triggered:
                if not self.notifier.is_stopped(symbol):
                    await self.notifier.send_message(alert_msg + f"\n(回覆 /stop {symbol} 暫停)")
            elif self.notifier.is_stopped(symbol):
                self.notifier.stopped_symbols.remove(symbol.upper())
            
            self.notion.update_price_and_status(item['page_id'], price, status)
            
        print(f"檢查完成。成功: {success_count}, 失敗: {fail_count}")
        return success_count, fail_count

    async def get_summary_callback(self, offset=0):
        items = self.notion.get_monitoring_list()
        if not items: return ""
        if offset > 0: return await self.get_detailed_summary(offset=offset)
        
        lines = []
        for item in items:
            symbol = item['symbol']
            price = item.get('current_price', '---')
            # 格式化價格為 1 位小數
            if isinstance(price, (int, float)):
                price_str = f"{price:.1f}"
            else:
                price_str = str(price)
                
            line = f"• **{item['name']}** ({symbol})\n  價: `{price_str}` | 限: `{item['low_alert']} ~ {item['high_alert']}`"
            if self.notifier.is_stopped(symbol): line += " (已暫停)"
            lines.append(line)
        return "\n\n".join(lines)

    async def change_alert_callback(self, symbol, high=None, low=None):
        items = self.notion.get_monitoring_list()
        target = next((i for i in items if i['symbol'].upper() == symbol.upper()), None)
        if target:
            self.notion.update_alert_prices(target['page_id'], high_alert=high, low_alert=low)
            return True
        return False

    async def get_report_data(self, offset=0):
        items = self.notion.get_monitoring_list()
        stock_list, date_str = [], "---"
        for item in items:
            symbol = item['symbol']
            stats = self.fetcher.get_full_stats(symbol, offset=offset)
            if stats:
                if date_str == "---": date_str = stats['date']
                ma_status = "📈 站上 MA20" if stats.get('close',0) >= stats.get('ma20',0) else "📉 跌破 MA20"
                stock_list.append({
                    "name": item['name'], "symbol": symbol, "close": stats.get('close', 0),
                    "change_pct": stats.get('change_pct', 0), "ma20_status": ma_status,
                    "open": stats.get('open', 0), "high": stats.get('high', 0), 
                    "low": stats.get('low', 0), "volume": stats.get('volume', 0)
                })
        
        sentiment_data = {
            "date": date_str, "time": "---", "sentiment": "---", 
            "diff_vol": 0, "overheat_index": 0
        }
        m_stats = self.fetcher.get_market_order_stats()
        if m_stats:
            total_buy = m_stats.get('total_buy_volume', 0)
            total_sell = m_stats.get('total_sell_volume', 0)
            diff_vol = total_buy - total_sell
            # 過熱指數公式：(累積成交數量 / 委託買進筆數) * 100
            overheat_val = (m_stats.get('total_deal_volume',0) / m_stats.get('total_buy_order', 1)) * 100
            sentiment_data = {
                "date": m_stats.get('date', date_str), "time": m_stats.get('time', '---'),
                "sentiment": "🐂 偏多" if diff_vol > 0 else "🐻 偏空" if diff_vol < 0 else "⚪ 持平",
                "diff_vol": diff_vol,
                "overheat_index": round(overheat_val, 2)
            }
        return {"date": date_str, "stock_list": stock_list, "sentiment": sentiment_data}

    async def get_detailed_summary(self, offset=0):
        data = await self.get_report_data(offset=offset)
        if not data['stock_list']: return "無法獲取資料。"
        lines = [f"📅 基準日期: `{data['date']}`\n"]
        for s in data['stock_list']:
            change_str = f"{'🔴' if s['change_pct']>0 else '🟢' if s['change_pct']<0 else '⚪'} {s['change_pct']}%"
            close_str = f"{s['close']:.1f}"
            lines.append(f"• **{s['name']}** ({s['symbol']})\n  收: `{close_str}` ({change_str})\n  量: `{s['volume']:,}` / MA20: {s['ma20_status']}")
        return "\n".join(lines)

    async def change_config_callback(self, interval=None, allow_outside=None):
        if interval: self.interval = interval
        if allow_outside is not None: self.allow_outside = allow_outside

    async def get_market_callback(self): return self.fetcher.get_market_indices()
    async def get_api_usage_callback(self): return None # FinMind removed

    async def get_stock_history_callback(self, symbol):
        stats_list = self.fetcher.get_five_day_stats(symbol)
        if not stats_list: return None
        lines = [f"📈 **{symbol} 近 5 日數據 (Fugle/YF)**\n"]
        for s in stats_list:
            close_val = s['close']
            close_str = f"{close_val:.1f}" if isinstance(close_val, (int, float)) else str(close_val)
            ma20_val = s.get('ma20')
            ma20_str = f"{ma20_val:.1f}" if isinstance(ma20_val, (int, float)) else "---"
            lines.append(f"📅 `{s['date']}` 開:`{s['open']:.1f}` 收:`{close_str}` 量:`{s['volume']:,}` MA20:`{ma20_str}`")
        return "\n".join(lines)

    async def get_graphical_report_callback(self, offset=0):
        data = await self.get_report_data(offset=offset)
        if not data['stock_list']: return None, "清單為空。"
        try:
            path = self.generator.generate_closing_report(data['sentiment'], data['stock_list'])
            return path, f"數據日期: `{data['date']}`"
        except: return None, "生成失敗。"

    async def get_stock_chart_callback(self, symbol):
        stats = self.fetcher.get_five_day_stats(symbol)
        if not stats: return None
        try: return self.generator.generate_stock_history_chart(symbol, stats)
        except: return None

    async def get_monitoring_limits_callback(self):
        items = self.notion.get_monitoring_list()
        if not items: return None
        lines = ["📋 **警報設定清單**\n"]
        for i in items:
            lines.append(f"• **{i['name']}** ({i['symbol']}) 上:{i['high_alert'] or '無'} 下:{i['low_alert'] or '無'}")
        return "\n".join(lines)

    async def test_report_callback(self, report_type):
        if report_type == "daily":
            data = await self.get_report_data(offset=0)
            if not data['stock_list']:
                await self.notifier.send_message("⚠️ 無法產生報表：目前監控清單為空或無法獲取任何資料。")
                return False
            try:
                path = self.generator.generate_closing_report(data['sentiment'], data['stock_list'])
                await self.notifier.send_photo(path, caption="🔔 **盤後綜合報告 (手動測試)**")
                return True
            except Exception as e:
                print(f"Daily Report Error: {e}")
                await self.notifier.send_message(f"❌ 報表產生失敗: {e}")
        return False

    async def run_monitor_loop(self):
        while True:
            try:
                now = self._get_now_taipei()
                today, curr_time = now.date(), now.time()
                is_weekday = now.weekday() <= 4

                if is_weekday:
                    # 15:00 盤後報告
                    if dt_time(15, 0) <= curr_time < dt_time(15, 20) and self.last_daily_report_date != today:
                        await self.test_report_callback("daily")
                        self.last_daily_report_date = today

                if self.is_market_open():
                    if time.time() - self.last_check_time >= self.interval:
                        await self.check_once()
                        self.last_check_time = time.time()
            except Exception as e: print(f"Loop Error: {e}")
            await asyncio.sleep(60)

    def run(self):
        self.notifier.set_data_callback(self.get_summary_callback)
        self.notifier.set_alert_callback(self.change_alert_callback)
        self.notifier.set_config_callback(self.change_config_callback)
        self.notifier.set_market_callback(self.get_market_callback)
        self.notifier.set_check_callback(self.check_once)
        self.notifier.set_stock_history_callback(self.get_stock_history_callback)
        self.notifier.set_test_callback(self.test_report_callback)
        self.notifier.set_report_callback(self.get_graphical_report_callback)
        self.notifier.set_stock_chart_callback(self.get_stock_chart_callback)
        self.notifier.set_monitoring_list_callback(self.get_monitoring_limits_callback)
        
        app = self.notifier.app
        if app:
            async def post_init(application): asyncio.create_task(self.run_monitor_loop())
            app.post_init = post_init
            app.run_polling()

if __name__ == "__main__":
    MarketMonitor().run()

import os
import asyncio
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

class Notifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.stopped_symbols = set() # 用於記錄暫停警戒的標的
        self.app = None
        
        if self.token:
            self.app = ApplicationBuilder().token(self.token).build()
            self.app.add_handler(CommandHandler("stop", self._stop_command))
            self.app.add_handler(CommandHandler("start", self._start_command))
            self.app.add_handler(CommandHandler("alist", self._alist_command))
            self.app.add_handler(CommandHandler("list", self._list_command))
            self.app.add_handler(CommandHandler("sethigh", self._set_high_command))
            self.app.add_handler(CommandHandler("setlow", self._set_low_command))
            self.app.add_handler(CommandHandler("interval", self._set_interval_command))
            self.app.add_handler(CommandHandler("mode", self._set_mode_command))
            self.app.add_handler(CommandHandler("prev", self._prev_command))
            self.app.add_handler(CommandHandler("market", self._market_command)) # New command
            self.app.add_handler(CommandHandler("check", self._check_command)) # New command
            self.app.add_handler(CommandHandler("apicheck", self._api_usage_command)) # New command
            self.app.add_handler(CommandHandler("test", self._test_command)) # New command for testing
            self.app.add_handler(CommandHandler("help", self._help_command))
            from telegram.ext import MessageHandler, filters
            self.app.add_handler(MessageHandler(filters.ALL, self._debug_handler))
            self.data_callback = None
            self.alert_callback = None
            self.config_callback = None
            self.market_callback = None # New callback
            self.check_callback = None # New callback
            self.api_usage_callback = None # New callback
            self.stock_history_callback = None # New callback
            self.test_callback = None # New callback

    async def _debug_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        pass

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """顯示功能的說明訊息"""
        try:
            help_text = (
                "🚀 **庫存股價格監控系統 - 指令指南**\n\n"
                "🔍 **即時查詢**\n"
                "• `/check` - 立即執行一次價格檢查與警報觸發\n"
                "• `/market` - 顯示全球指數 (台/美股、能源、匯率、加密貨幣)\n"
                "• `/list [代碼]` - 查詢標的近 5 日詳細 K 線與 MA 數據\n"
                "• `/apicheck` - 查詢 API 剩餘額度與備援狀態\n"
                "• `/test [類別]` - 手動測試報告 (noon/sentiment/daily)\n\n"
                "📋 **監控與報告**\n"
                "• `/show` - 顯示目前所有監控中的標的報價清單\n"
                "• `/prev` - 顯示前一交易日的完整盤後總結報告\n"
                "• `/alist` - 顯示目前「已暫停警報」的標的清單\n\n"
                "⚙️ **警報管理**\n"
                "• `/stop [代碼]` - 暫停特定標的的價格警報 (例如: `/stop 2330`)\n"
                "• `/start [代碼]` - 恢復特定標的的價格警報\n\n"
                "💡 **自動化通知**\n"
                "• 09:00 - 開盤提醒\n"
                "• 12:00 - 大盤午間報告 (含 MA20 判定)\n"
                "• 14:00 - 盤後綜合大報告 (收盤總結 + 買賣力道 + 詳細數據)\n\n"
                "⚠️ *系統預設每 30 分鐘自動檢查一次報價*。"
            )
            await update.message.reply_text(help_text, parse_mode='Markdown')
        except Exception as e:
            print(f"發送 Help 訊息時發生錯誤: {e}")

    async def _prev_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.data_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
            
        try:
            # 請求前一交易日資料
            summary = await self.data_callback(offset=1)
            if not summary:
                await update.message.reply_text("無法獲取前一交易日資料 (可能資料尚未更新或 API 限制)。")
            else:
                await update.message.reply_text(f"📊 **前一交易日收盤報告**\n\n{summary}", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ 執行 /prev 時發生錯誤: {e}")
            print(f"Error in _prev_command: {e}")

    def set_data_callback(self, callback):
        """設定用於獲取標的摘要的回呼函式"""
        self.data_callback = callback

    def set_alert_callback(self, callback):
        """設定用於更新警戒價格的回呼函式"""
        self.alert_callback = callback

    def set_config_callback(self, callback):
        """設定用於更新系統配置的回呼函式"""
        self.config_callback = callback
        
    def set_market_callback(self, callback):
        """設定用於獲取市場指數的回呼函式"""
        self.market_callback = callback

    def set_check_callback(self, callback):
        """設定用於立即檢查價格的回呼函式"""
        self.check_callback = callback

    def set_api_usage_callback(self, callback):
        """設定用於獲取 API 使用量的回呼函式"""
        self.api_usage_callback = callback

    def set_stock_history_callback(self, callback):
        """設定用於獲取股票歷史數據的回呼函式"""
        self.stock_history_callback = callback
    
    def set_test_callback(self, callback):
        """設定用於手動測試報告的回呼函式"""
        self.test_callback = callback

    async def _set_interval_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("請提供秒數，例如：/interval 300")
            return
        
        try:
            seconds = int(context.args[0])
            if seconds < 60:
                await update.message.reply_text("為了避免被 API 封鎖，間隔請至少設定為 60 秒。")
                return
            
            if self.config_callback:
                await self.config_callback(interval=seconds)
                await update.message.reply_text(f"✅ 已將檢查間隔更新為 {seconds} 秒。")
        except ValueError:
            await update.message.reply_text("請輸入有效的數字。")

    async def _set_mode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("請提供參數，例如：/mode on 或 /mode off")
            return
        
        mode = context.args[0].lower()
        allow = True if mode == "on" else False
        
        if self.config_callback:
            await self.config_callback(allow_outside=allow)
            status = "開啟" if allow else "關閉"
            await update.message.reply_text(f"✅ 已{status}交易時段外監控。")

    async def _set_high_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.args) < 2:
            await update.message.reply_text("請提供代碼與價格，例如：/sethigh 2330 1100")
            return
        
        symbol, price = context.args[0].upper(), context.args[1]
        try:
            price = float(price)
            if self.alert_callback:
                success = await self.alert_callback(symbol, high=price)
                if success:
                    await update.message.reply_text(f"✅ 已將 {symbol} 的上限警戒值設定為 {price}")
                else:
                    await update.message.reply_text(f"❌ 找不到代碼 {symbol}")
        except ValueError:
            await update.message.reply_text("價格請輸入數字。")

    async def _set_low_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.args) < 2:
            await update.message.reply_text("請提供代碼與價格，例如：/setlow 2330 900")
            return
        
        symbol, price = context.args[0].upper(), context.args[1]
        try:
            price = float(price)
            if self.alert_callback:
                success = await self.alert_callback(symbol, low=price)
                if success:
                    await update.message.reply_text(f"✅ 已將 {symbol} 的下限警戒值設定為 {price}")
                else:
                    await update.message.reply_text(f"❌ 找不到代碼 {symbol}")
        except ValueError:
            await update.message.reply_text("價格請輸入數字。")

    async def _show_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.data_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
            
        try:
            # 支援 /show list 作為別名
            show_type = "all"
            if context.args and context.args[0].lower() == "list":
                show_type = "list"
                
            summary = await self.data_callback()
            if not summary:
                await update.message.reply_text("目前的監控清單為空。")
            else:
                title = "📊 **目前監控清單摘要**" if show_type != "list" else "📋 **目前監控清單**"
                await update.message.reply_text(f"{title}\n\n{summary}", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ 執行 /show 時發生錯誤: {e}")
            print(f"Error in _show_command: {e}")

    async def _market_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.market_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
        
        try:
            await update.message.reply_text("🔄 正從國際市場獲取數據中...")
            market_data = await self.market_callback()
            
            if not market_data:
                await update.message.reply_text("無法獲取市場數據。")
                return

            lines = []
            for item in market_data:
                price_str = f"{item['price']:,.2f}"
                change_str = foo = f"{item['change_pct']:+.2f}%"
                lines.append(f"{item['name']}: `{price_str}` ({item['emoji']} {change_str})")
            
            msg = "🌍 **全球重要市場指數**\n\n" + "\n".join(lines)
            await update.message.reply_text(msg, parse_mode='Markdown')
            
        except Exception as e:
             await update.message.reply_text(f"❌ 執行 /market 時發生錯誤: {e}")
             print(f"Error in _market_command: {e}")

    async def _check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.check_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
        
        try:
            await update.message.reply_text("🔄 正在執行手動價格檢查...")
            success, fail = await self.check_callback()
            
            if success == 0 and fail == 0:
                msg = "📝 監控清單為空，未執行檢查。"
            elif fail == 0:
                msg = f"✅ 檢查完成！成功更新 {success} 檔標的。"
            elif success == 0:
                msg = f"❌ 檢查失敗。共 {fail} 檔標的獲取數據失敗，請檢查 API 限制或 Token 設定。"
            else:
                msg = f"⚠️ 檢查部分完成。成功: {success}, 失敗: {fail}。\n(部分標的可能已達 API 上限)"
                
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ 執行檢查時發生錯誤: {e}")
            print(f"Error in _check_command: {e}")

    async def _api_usage_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.api_usage_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
        
        try:
            usage = await self.api_usage_callback()
            if not usage:
                await update.message.reply_text("無法獲取 API 使用資訊，可能是未設定 Token。")
            else:
                current = usage['user_count']
                limit = usage['api_request_limit']
                percent = round((current / limit) * 100, 2) if limit > 0 else 0
                msg = (
                    "📊 **FinMind API 使用量查詢**\n\n"
                    f"• 目前已使用: `{current}`\n"
                    f"• 每小時上限: `{limit}`\n"
                    f"• 已用百分比: `{percent}%`"
                )
                
                # 增加富果備援顯示
                fugle_key = os.getenv("FUGLE_API_TOKEN") or os.getenv("富果API KEY") or os.getenv("富果API_KEY")
                fugle_status = "✅ 已設定" if fugle_key else "❌ 未設定"
                msg += f"\n\n🛠️ **備援系統**\n• 富果 Fugle API: {fugle_status}"
                
                await update.message.reply_text(msg, parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ 查詢時發生錯誤: {e}")
            print(f"Error in _api_usage_command: {e}")

    async def _stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("請提供要停止的代碼，例如：/stop 2330")
            return
        
        symbol = context.args[0].upper()
        self.stopped_symbols.add(symbol)
        await update.message.reply_text(f"已停止 {symbol} 的持續警報。如需重啟請輸入 /start {symbol}")

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("請提供要啟動的代碼，例如：/start 2330")
            return
            
        symbol = context.args[0].upper()
        if symbol in self.stopped_symbols:
            self.stopped_symbols.remove(symbol)
            await update.message.reply_text(f"已恢復 {symbol} 的持續警報。")
        else:
            await update.message.reply_text(f"{symbol} 目前不在停止清單中。")

    async def _list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("請提供要查詢的代碼，例如：/list 2330")
            return
            
        # 如果有提供代碼，執行查詢五日數據功能
        symbol = context.args[0].upper()
        if not self.stock_history_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
        
        try:
            await update.message.reply_text(f"🔄 正在查詢 {symbol} 的五日數據...")
            history_msg = await self.stock_history_callback(symbol)
            if not history_msg:
                await update.message.reply_text(f"找不到 {symbol} 的數據或 API 暫時無法連線。")
            else:
                await update.message.reply_text(history_msg, parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ 查詢時發生錯誤: {e}")
            print(f"Error in _list_command (history): {e}")

    async def _alist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """顯示目前的暫停警報清單"""
        if not self.stopped_symbols:
            await update.message.reply_text("目前沒有停止任何警報。")
        else:
            await update.message.reply_text(f"目前停止警報清單：{', '.join(self.stopped_symbols)}")

    async def _test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """手動觸發測試報告"""
        if not self.test_callback:
            await update.message.reply_text("系統尚未準備好。")
            return
            
        if not context.args:
            await update.message.reply_text("請指定測試類別：\n`/test noon` - 午間大盤\n`/test sentiment` - 買賣力道\n`/test daily` - 標的總結", parse_mode='Markdown')
            return
            
        action = context.args[0].lower()
        await update.message.reply_text(f"正在生成測試報告: {action}...")
        success = await self.test_callback(action)
        if not success:
            await update.message.reply_text(f"❌ 測試報告生成失敗，請檢查類別名稱或 API 狀態。")

    async def start_listening(self):
        """啟動機器人監聽指令"""
        if self.app:
            await self.app.initialize()
            await self.app.start()
            # 這裡我們不使用 run_polling() 因為它會阻塞，
            # 我們改用更底層的方式在外部循環中處理 updater
            from telegram.ext import ExtBot
            await self.app.updater.start_polling()
            print("Telegram 機器人指令監聽已啟動...")

    async def send_message(self, text):
        if not self.app or not self.chat_id:
            print("Telegram 未設定，無法發送訊息")
            print(f"內容: {text}")
            return

        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text, parse_mode='Markdown')
            print(f"Telegram 訊息已發送: {text}")
        except Exception as e:
            print(f"發送 Telegram 訊息時發生錯誤: {e}")

    def is_stopped(self, symbol):
        return symbol.upper() in self.stopped_symbols


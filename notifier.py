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
            self.app.add_handler(CommandHandler("help", self._help_command))
            from telegram.ext import MessageHandler, filters
            self.app.add_handler(MessageHandler(filters.ALL, self._debug_handler))
            self.data_callback = None
            self.alert_callback = None
            self.config_callback = None
            self.market_callback = None # New callback
            self.stock_history_callback = None # New callback

    async def _debug_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        pass

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            help_text = (
                "📌 可用指令清單\n\n"
                "🔍 查詢功能\n"
                "• /show all - 顯示目前 Notion 中所有標的摘要\n"
                "• /show list - 顯示目前監控清單 (同上)\n"
                "• /market - 顯示主要市場指數 (台股、美股、貴金屬)\n"
                "• /prev - 顯示前一交易日的完整收盤報告\n"
                "• /list [代碼] - 顯示代碼近五日詳細數據\n"
                "• /alist - 顯示目前已暫停警報的清單\n\n"
                "⚙️ 設定功能\n"
                "• /sethigh [代碼] [價格] - 設定上限警戒值\n"
                "• /setlow [代碼] [價格] - 設定下限警戒值\n"
                "• /interval [秒數] - 設定檢查頻率 (至少 60 秒)\n"
                "• /mode [on/off] - 是否開啟交易時段外監控\n\n"
                "🔔 警報控制\n"
                "• /stop [代碼] - 暫停特定標的的持續警報\n"
                "• /start [代碼] - 恢復特定標的的監控\n\n"
                "❔ /help - 顯示此說明訊息"
            )
            await update.message.reply_text(help_text)
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

    def set_stock_history_callback(self, callback):
        """設定用於獲取股票歷史數據的回呼函式"""
        self.stock_history_callback = callback

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


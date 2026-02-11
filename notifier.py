import os
import time
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
            self.app.add_handler(CommandHandler("dlist", self._dlist_command))
            self.app.add_handler(CommandHandler("add", self._add_command))
            self.app.add_handler(CommandHandler("sethigh", self._set_high_command))
            self.app.add_handler(CommandHandler("setlow", self._set_low_command))
            self.app.add_handler(CommandHandler("settime", self._set_interval_command))
            self.app.add_handler(CommandHandler("mode", self._set_mode_command))
            self.app.add_handler(CommandHandler("prev", self._prev_command))
            self.app.add_handler(CommandHandler("show", self._show_command))
            self.app.add_handler(CommandHandler("showlist", self._show_list_command))
            self.app.add_handler(CommandHandler("market", self._market_command))
            self.app.add_handler(CommandHandler("check", self._check_command))
            self.app.add_handler(CommandHandler("daily", self._daily_command))
            self.app.add_handler(CommandHandler("test", self._test_command))
            self.app.add_handler(CommandHandler("help", self._help_command))
            
            from telegram.ext import MessageHandler, filters
            self.app.add_handler(MessageHandler(filters.ALL, self._debug_handler))
            
            self.data_callback = None
            self.alert_callback = None
            self.config_callback = None
            self.market_callback = None
            self.check_callback = None
            self.stock_history_callback = None
            self.test_callback = None
            self.report_callback = None
            self.stock_chart_callback = None
            self.monitoring_list_callback = None
            self.add_item_callback = None

    async def _debug_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        pass

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """顯示功能的說明訊息"""
        try:
            help_text = (
                "🚀 **極簡股票價格監控系統 - 指令指南**\n\n"
                "🔍 **即時查詢**\n"
                "• `/check` - 立即執行一次價格檢查與警報觸發\n"
                "• `/list [代碼]` - 查詢標的近 5 日詳細數據 (文字)\n"
                "• `/dlist [代碼]` - 查詢標的近 5 日 K 線圖 (圖片)\n"
                "• `/market` - 查詢全球市場指數點位\n"
                "• `/test [類別]` - 手動測試報告 (noon/sentiment/daily)\n\n"
                "📋 **監控與報告**\n"
                "• `/show` - 顯示目前所有監控中的標的報價清單\n"
                "• `/showlist` - 顯示目前所有追蹤標的與警報上下限\n"
                "• `/daily` - 立即產生今日監控標的收盤總結報告\n"
                "• `/prev` - 顯示前一交易日的完整盤後總結報告\n"
                "• `/alist` - 顯示目前「已暫停警報」的標的清單\n\n"
                "⚙️ **警報管理**\n"
                "• `/add [代碼] [名稱] [上限] [下限]` - 新增監控標的\n"
                "  (註：名稱若輸入 `-` 則會自動抓取，範例：`/add 2330 - 1100 900`)\n"
                "• `/stop [代碼]` - 暫停特定標的的價格警報\n"
                "• `/start [代碼]` - 恢復特定標的的價格警報\n"
                "• `/sethigh [代碼] [價]` - 設定上限警報\n"
                "• `/setlow [代碼] [價]` - 設定下限警報\n\n"
                "⚙️ **系統設定**\n"
                "• `/settime [秒數]` - 設定報價檢查間隔 (例如: `/settime 300`)\n"
                "• `/mode [on/off]` - 切換是否在非交易時段監控\n\n"
                "💡 **自動化通知**\n"
                "• 09:00 - 開盤提醒\n"
                "• 12:00 - 大盤午間報告\n"
                "• 15:00 - 盤後綜合大報告 (收盤總結 + 買賣力道 + 詳細數據)\n"
            )
            await update.message.reply_text(help_text, parse_mode='Markdown')
        except Exception as e:
            print(f"發送 Help 訊息時發生錯誤: {e}")

    async def _prev_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.data_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
            
        try:
            if self.report_callback:
                await update.message.reply_text("正在產生前一交易日圖形化報告...")
                img_path, caption = await self.report_callback(offset=1)
                if img_path:
                    await self.send_photo(img_path, caption=f"📊 **前一交易日收盤報告**\n{caption}")
                    return
            
            summary = await self.data_callback(offset=1)
            if not summary:
                await update.message.reply_text("無法獲取前一交易日資料。")
            else:
                await update.message.reply_text(f"📊 **前一交易日收盤報告**\n\n{summary}", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ 執行時發生錯誤: {e}")

    def set_data_callback(self, callback): self.data_callback = callback
    def set_alert_callback(self, callback): self.alert_callback = callback
    def set_config_callback(self, callback): self.config_callback = callback
    def set_market_callback(self, callback): self.market_callback = callback
    def set_check_callback(self, callback): self.check_callback = callback
    def set_stock_history_callback(self, callback): self.stock_history_callback = callback
    def set_test_callback(self, callback): self.test_callback = callback
    def set_report_callback(self, callback): self.report_callback = callback
    def set_stock_chart_callback(self, callback): self.stock_chart_callback = callback
    def set_monitoring_list_callback(self, callback): self.monitoring_list_callback = callback
    def set_add_item_callback(self, callback): self.add_item_callback = callback

    async def _add_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text(
                "💡 指令格式：`/add [代碼] [名稱] [上限價] [下限價]`\n"
                "• 名稱輸入 `-` 則自動抓取\n"
                "• 範例：`/add 2330 台積電 1100 900`\n"
                "• 範例：`/add 2330 - 1100 900`"
            )
            return
        
        try:
            symbol = context.args[0].upper()
            # 判斷名稱參數
            provided_name = context.args[1] if len(context.args) > 1 else "-"
            # 如果為 "-"，代表要自動抓取，傳 None 給 callback
            final_name = None if provided_name == "-" else provided_name
            
            high = float(context.args[2]) if len(context.args) > 2 else None
            low = float(context.args[3]) if len(context.args) > 3 else None
            
            if self.add_item_callback:
                await update.message.reply_text(f"⏳ 正在嘗試新增 {symbol}...")
                success, name = await self.add_item_callback(symbol, high, low, custom_name=final_name)
                if success:
                    await update.message.reply_text(f"✅ 成功新增標的！\n代碼：`{symbol}`\n名稱：`{name}`\n上限：`{high or '無'}`\n下限：`{low or '無'}`")
                else:
                    await update.message.reply_text(f"❌ 新增失敗，請檢查代碼是否正確或系統日誌。")
        except Exception as e:
             await update.message.reply_text(f"❌ 格式錯誤：{e}\n請確保代碼後方跟著名稱(或-)及數字價位。")

    async def _set_interval_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("指令格式：`/settime [秒數]`")
            return
        try:
            seconds = int(context.args[0])
            if seconds < 60:
                await update.message.reply_text("⚠️ 間隔請至少設定為 **60** 秒。")
                return
            if self.config_callback:
                await self.config_callback(interval=seconds)
                await update.message.reply_text(f"✅ 自動檢查間隔已更變為：`{seconds}` 秒。")
        except:
            await update.message.reply_text("❌ 請輸入有效的數字。")

    async def _set_mode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("💡 指令格式：`/mode on` (全天候) 或 `/mode off` (交易時段)")
            return
        allow = context.args[0].lower() in ["on", "true", "1"]
        if self.config_callback:
            await self.config_callback(allow_outside=allow)
            status = "開啟 [全天候監控]" if allow else "關閉 [僅限交易時段]"
            await update.message.reply_text(f"✅ 設定成功：已切換為 {status}。")

    async def _set_high_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.args) < 2: return
        symbol, price = context.args[0].upper(), context.args[1]
        try:
            price = float(price)
            if self.alert_callback:
                if await self.alert_callback(symbol, high=price):
                    await update.message.reply_text(f"✅ {symbol} 上限警戒值已設定為 {price}")
        except: pass

    async def _set_low_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.args) < 2: return
        symbol, price = context.args[0].upper(), context.args[1]
        try:
            price = float(price)
            if self.alert_callback:
                if await self.alert_callback(symbol, low=price):
                    await update.message.reply_text(f"✅ {symbol} 下限警戒值已設定為 {price}")
        except: pass

    async def _market_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.market_callback: return
        try:
            await update.message.reply_text("🔄 正從國際市場獲取數據中...")
            market_data = await self.market_callback()
            if not market_data:
                await update.message.reply_text("無法獲取市場數據。")
                return
            lines = [f"{i['name']}: `{i['price']:,.2f}` ({i['emoji']} {i['change_pct']:+.2f}%)" for i in market_data]
            await update.message.reply_text("🌍 **全球重要市場指數**\n\n" + "\n".join(lines), parse_mode='Markdown')
        except: pass

    async def _check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.check_callback: return
        try:
            await update.message.reply_text("🔄 執行手動檢查 (Fugle API)...")
            success, fail = await self.check_callback(force=True)
            await update.message.reply_text(f"✅ 檢查完成！成功: {success}, 失敗: {fail}")
        except: pass

    async def _stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args: return
        symbol = context.args[0].upper()
        self.stopped_symbols.add(symbol)
        await update.message.reply_text(f"已停止 {symbol} 警報。")

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args: return
        symbol = context.args[0].upper()
        if symbol in self.stopped_symbols:
            self.stopped_symbols.remove(symbol)
            await update.message.reply_text(f"已恢復 {symbol} 警報。")

    async def _list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args: return
        symbol = context.args[0].upper()
        if not self.stock_history_callback: return
        await update.message.reply_text(f"🔄 查詢 {symbol} 五日數據...")
        history_msg = await self.stock_history_callback(symbol)
        if history_msg: await update.message.reply_text(history_msg, parse_mode='Markdown')

    async def _dlist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args: return
        symbol = context.args[0].upper()
        if not self.stock_chart_callback: return
        await update.message.reply_text(f"📊 產生 {symbol} K 線圖...")
        img_path = await self.stock_chart_callback(symbol)
        if img_path: await self.send_photo(img_path, caption=f"📈 **{symbol} 五日 K 線圖**")

    async def _alist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.stopped_symbols:
            await update.message.reply_text("目前沒有暫停的警報。")
        else:
            await update.message.reply_text(f"暫停清單：{', '.join(self.stopped_symbols)}")

    async def _show_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.data_callback: return
        try:
            if self.report_callback:
                await update.message.reply_text("正在產生成績單...")
                img_path, caption = await self.report_callback(offset=0)
                if img_path:
                    await self.send_photo(img_path, caption=f"🚀 **即時報價總覽**\n{caption}")
                    return
            summary = await self.data_callback()
            if summary: await update.message.reply_text(f"🚀 **即時報價總覽**\n\n{summary}", parse_mode='Markdown')
        except: pass

    async def _show_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.monitoring_list_callback: return
        msg = await self.monitoring_list_callback()
        if msg: await update.message.reply_text(msg, parse_mode='Markdown')

    async def _test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.test_callback or not context.args: return
        action = context.args[0].lower()
        await self.test_callback(action)

    async def _daily_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.test_callback: return
        await update.message.reply_text("📊 正在產生收盤報告...")
        await self.test_callback("daily")

    async def start_listening(self):
        if self.app:
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling()
            print("Telegram 指令監聽啟動 (極簡化)")

    async def send_message(self, text):
        if not self.app or not self.chat_id: return
        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text, parse_mode='Markdown')
        except: pass

    async def send_photo(self, photo_path, caption=None):
        if not self.app or not self.chat_id: return
        try:
            with open(photo_path, 'rb') as photo:
                await self.app.bot.send_photo(chat_id=self.chat_id, photo=photo, caption=caption, parse_mode='Markdown')
        except: pass

    def is_stopped(self, symbol): return symbol.upper() in self.stopped_symbols

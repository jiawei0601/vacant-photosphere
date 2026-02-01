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
            self.app.add_handler(CommandHandler("sethigh", self._set_high_command))
            self.app.add_handler(CommandHandler("setlow", self._set_low_command))
            self.app.add_handler(CommandHandler("interval", self._set_interval_command))
            self.app.add_handler(CommandHandler("settime", self._set_interval_command))
            self.app.add_handler(CommandHandler("mode", self._set_mode_command))
            self.app.add_handler(CommandHandler("prev", self._prev_command))
            self.app.add_handler(CommandHandler("show", self._show_command))
            self.app.add_handler(CommandHandler("showlist", self._show_list_command))
            self.app.add_handler(CommandHandler("market", self._market_command))
            self.app.add_handler(CommandHandler("check", self._check_command)) # New command
            self.app.add_handler(CommandHandler("apicheck", self._api_usage_command)) # New command
            self.app.add_handler(CommandHandler("test", self._test_command)) # New command for testing
            self.app.add_handler(CommandHandler("sync", self._sync_command)) # New command
            self.app.add_handler(CommandHandler("help", self._help_command))
            from telegram.ext import MessageHandler, filters
            self.app.add_handler(MessageHandler(filters.PHOTO, self._photo_handler))
            self.app.add_handler(MessageHandler(filters.ALL, self._debug_handler))
            self.data_callback = None
            self.alert_callback = None
            self.config_callback = None
            self.market_callback = None # New callback
            self.check_callback = None # New callback
            self.api_usage_callback = None # New callback
            self.stock_history_callback = None # New callback
            self.test_callback = None # New callback
            self.report_callback = None # New callback
            self.stock_chart_callback = None # New callback
            self.monitoring_list_callback = None # New callback
            self.inventory_callback = None # New callback for OCR
            self.fubon_sync_callback = None # New callback for Fubon API Sync
            self.ocr_usage_callback = None # New callback for OCR usage

    async def _debug_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        pass

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """顯示功能的說明訊息"""
        try:
            help_text = (
                "🚀 **庫存股價格監控系統 - 指令指南**\n\n"
                "🔍 **即時查詢**\n"
                "• `/check` - 立即執行一次價格檢查與警報觸發\n"
                "• `/list [代碼]` - 查詢標的近 5 日詳細 K 線數據 (文字)\n"
                "• `/dlist [代碼]` - 查詢標的近 5 日 K 線變化 (圖片)\n"
                "• `/apicheck` - 查詢 API 剩餘額度與備援狀態\n"
                "• `/test [類別]` - 手動測試報告 (noon/sentiment/daily)\n\n"
                "📋 **監控與報告**\n"
                "• `/show` - 顯示目前所有監控中的標的報價清單\n"
                "• `/showlist` - 顯示目前所有追蹤標的與警報上下限\n"
                "• `/prev` - 顯示前一交易日的完整盤後總結報告\n"
                "• `/sync` - **[New]** 從富邦 API 自動同步最新庫存 (需先配置)\n"
                "• `/alist` - 顯示目前「已暫停警報」的標的清單\n\n"
                "📷 **庫存更新**\n"
                "• 直接傳送「庫存截圖」給機器人，系統會自動透過 OCR 解析並更新 Notion 資料庫。\n\n"
                "⚙️ **警報管理**\n"
                "• `/stop [代碼]` - 暫停特定標的的價格警報 (例如: `/stop 2330`)\n"
                "• `/start [代碼]` - 恢復特定標的的價格警報\n\n"
                "⚙️ **系統設定**\n"
                "• `/settime [秒數]` - 設定報價檢查間隔 (例如: `/settime 300`)\n"
                "• `/mode [on/off]` - 切換是否在非交易時段監控\n\n"
                "💡 **自動化通知**\n"
                "• 09:00 - 開盤提醒\n"
                "• 12:00 - 大盤午間報告 (含 MA20 判定)\n"
                "• 15:00 - 盤後綜合大報告 (收盤總結 + 買賣力道 + 詳細數據)\n\n"
                "⚠️ *目前報價檢查間隔可透過 /settime 修改*。"
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
            
            # Fallback to text
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

    def set_report_callback(self, callback):
        """設定用於獲取圖形化報告回呼函式"""
        self.report_callback = callback
    
    def set_stock_chart_callback(self, callback):
        """設定用於獲取股票 K 線圖回呼函式"""
        self.stock_chart_callback = callback
    
    def set_monitoring_list_callback(self, callback):
        """設定用於獲取監控清單回呼函式"""
        self.monitoring_list_callback = callback

    def set_inventory_callback(self, callback):
        """設定用於庫存 OCR 的回呼函式"""
        self.inventory_callback = callback

    def set_ocr_usage_callback(self, callback):
        """設定用於獲取 OCR 使用量的回呼函式"""
        self.ocr_usage_callback = callback

    def set_fubon_sync_callback(self, callback):
        """設定用於富邦 API 同步的回呼函式"""
        self.fubon_sync_callback = callback

    async def _set_interval_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """處理 /settime 指令，設定自動檢查間隔"""
        if not context.args:
            await update.message.reply_text("💡 **設定自動檢查時間**\n\n指令格式：`/settime [秒數]`\n例如：\n• `/settime 300` (設定為 5 分鐘)\n• `/settime 600` (設定為 10 分鐘)\n\n*注意：間隔最快不得低於 60 秒。*")
            return
        
        try:
            seconds = int(context.args[0])
            if seconds < 60:
                await update.message.reply_text("⚠️ 為了避免 API 存取過於頻繁導致封鎖，間隔請至少設定為 **60** 秒。")
                return
            
            if self.config_callback:
                await self.config_callback(interval=seconds)
                mins = round(seconds / 60, 1)
                await update.message.reply_text(f"✅ **設定成功**\n自動價格檢查間隔已更變為：`{seconds}` 秒 (約 {mins} 分鐘)。")
        except ValueError:
            await update.message.reply_text("❌ 請輸入有效的數字（秒數）。")

    async def _set_mode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """處理 /mode 指令，切換交易時段外監控"""
        if not context.args:
            # 如果沒給參數，顯示目前狀態
            if self.config_callback:
                # 這裡需要一個獲取狀態的方式，或者我們直接在 notifier 存一份
                pass
            await update.message.reply_text("💡 目前模式選項：\n• `/mode on` 或 `/mode true` - 開啟全天候監控\n• `/mode off` 或 `/mode false` - 僅在交易時段 (09:00-13:35) 監控")
            return
        
        mode = context.args[0].lower()
        allow = mode in ["on", "true", "1"]
        
        if self.config_callback:
            await self.config_callback(allow_outside=allow)
            status = "開啟 [全天候監控]" if allow else "關閉 [僅限交易時段]"
            await update.message.reply_text(f"✅ 設定成功：已切換為 {status}。\n\n目前的交易時段設定為：週一至週五 09:00 - 13:35。")

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

    async def _sync_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """處理 /sync 指令，觸發富邦 API 同步"""
        if not self.fubon_sync_callback:
            await update.message.reply_text("系統尚未設定富邦 API 同步功能。")
            return
            
        await update.message.reply_text("🔄 正在從富邦證券 API 同步庫存資料，請稍候...")
        result_msg = await self.fubon_sync_callback()
        await update.message.reply_text(result_msg, parse_mode='Markdown')

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
                
                # 增加 OCR 使用量顯示
                if self.ocr_usage_callback:
                    ocr_usage = await self.ocr_usage_callback()
                    msg += f"\n\n{ocr_usage}"
                
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

    async def _dlist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("請提供要查詢的代碼，例如：/dlist 2330")
            return
            
        symbol = context.args[0].upper()
        if not self.stock_chart_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
            
        try:
            await update.message.reply_text(f"📊 正在產生 {symbol} 的五日 K 線圖...")
            img_path = await self.stock_chart_callback(symbol)
            if not img_path:
                await update.message.reply_text(f"找不到 {symbol} 的數據或圖片生成失敗。")
            else:
                await self.send_photo(img_path, caption=f"📈 **{symbol} 五日 K 線變化圖**")
        except Exception as e:
            await update.message.reply_text(f"❌ 查詢時發生錯誤: {e}")
            print(f"Error in _dlist_command: {e}")

    async def _alist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """顯示目前的暫停警報清單"""
        if not self.stopped_symbols:
            await update.message.reply_text("目前沒有停止任何警報。")
        else:
            await update.message.reply_text(f"目前停止警報清單：{', '.join(self.stopped_symbols)}")

    async def _show_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """顯示目前監控標的的即時報告"""
        if not self.data_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
            
        try:
            if self.report_callback:
                await update.message.reply_text("正在產生即時圖形化報告...")
                img_path, caption = await self.report_callback(offset=0)
                if img_path:
                    await self.send_photo(img_path, caption=f"🚀 **目前監控標的即時報價**\n{caption}")
                    return

            summary = await self.data_callback()
            if not summary:
                await update.message.reply_text("目前監控清單為空。")
            else:
                await update.message.reply_text(f"🚀 **目前監控標的即時報價**\n\n{summary}", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ 查詢時發生錯誤: {e}")
            print(f"Error in _show_command: {e}")

    async def _show_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """顯示目前追蹤標的與上下限清單"""
        if not self.monitoring_list_callback:
            await update.message.reply_text("系統尚未準備好，請稍後再試。")
            return
            
        try:
            msg = await self.monitoring_list_callback()
            if not msg:
                await update.message.reply_text("目前監控清單為空。")
            else:
                await update.message.reply_text(msg, parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ 查詢清單時發生錯誤: {e}")
            print(f"Error in _show_list_command: {e}")

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

    async def _photo_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """處理接收到的圖片，進行 OCR 辨識"""
        if not self.inventory_callback:
            await update.message.reply_text("系統尚未設定庫存解析功能。")
            return

        try:
            await update.message.reply_text("🖼️ 接收到圖片，正在準備進行 OCR 辨識 (Google Cloud Vision)，請稍候...")
            
            # 下載圖片
            photo_file = await update.message.photo[-1].get_file()
            
            # 建立暫存目錄
            temp_dir = "temp_images"
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            
            file_extension = ".jpg"
            file_path = os.path.join(temp_dir, f"ocr_{int(time.time())}{file_extension}")
            await photo_file.download_to_drive(file_path)
            
            # 呼叫回呼函數進行解析與更新
            results = await self.inventory_callback(file_path, upload_date=time.strftime("%Y-%m-%d"))
            
            if not results:
                await update.message.reply_text("❌ OCR 辨識失敗或找不到有效的標的代碼。")
            else:
                summary = "✅ **庫存更新結果**\n\n"
                for s in results:
                    # 清理名稱中的 Markdown 特殊字元避免 Telegram 報錯
                    safe_name = s['name'].replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
                    summary += f"• {safe_name} ({s['symbol']}) - {s['status']}\n"
                
                # 額外附上使用量報告
                if self.ocr_usage_callback:
                    usage_msg = await self.ocr_usage_callback()
                    summary += f"\n---\n{usage_msg}"
                
                await update.message.reply_text(summary, parse_mode='Markdown')
            
            # 刪除暫存檔
            if os.path.exists(file_path):
                os.remove(file_path)
                
        except Exception as e:
            await update.message.reply_text(f"❌ 處理圖片時發生錯誤: {e}")
            print(f"Error in _photo_handler: {e}")

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
            print(f"Telegram 訊息已發送 (文字)")
        except Exception as e:
            print(f"發送 Telegram 訊息時發生錯誤: {e}")

    async def send_photo(self, photo_path, caption=None):
        if not self.app or not self.chat_id:
            print("Telegram 未設定，無法發送圖片")
            return

        try:
            with open(photo_path, 'rb') as photo:
                await self.app.bot.send_photo(chat_id=self.chat_id, photo=photo, caption=caption, parse_mode='Markdown')
            print(f"Telegram 圖片已發送: {photo_path}")
        except Exception as e:
            print(f"發送 Telegram 圖片時發生錯誤: {e}")

    def is_stopped(self, symbol):
        return symbol.upper() in self.stopped_symbols


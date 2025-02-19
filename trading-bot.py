import MetaTrader5 as mt5
import sqlite3
import pandas as pd
import telegram
from telegram.ext import Updater, CommandHandler
import ta  

# Conectar con MetaTrader 5
mt5.initialize()

# Configurar Telegram
TOKEN = 'TU_TOKEN_TELEGRAM'
updater = Updater(token=TOKEN, use_context=True)
dispatcher = updater.dispatcher
bot = telegram.Bot(token=TOKEN)

# Base de datos
conn = sqlite3.connect('trading_bot.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        action TEXT,
        lot REAL,
        sl REAL,
        tp REAL,
        profit REAL,
        open_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        close_time TIMESTAMP,
        result TEXT
    )
''')
conn.commit()

# Variables globales
lot_size = 0.1
max_open_trades = 5
symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP"]
open_trades = []

### 📌 NOTIFICAR CUANDO SE ABRE UNA OPERACIÓN ###
def notify_trade_open(symbol, action, lot, sl, tp, price):
    message = f"📢 *Nueva operación abierta*\n\n" \
              f"📌 *Par*: {symbol}\n" \
              f"🔹 *Acción*: {action.upper()}\n" \
              f"📊 *Lote*: {lot}\n" \
              f"📉 *Stop Loss*: {sl}\n" \
              f"📈 *Take Profit*: {tp}\n" \
              f"💰 *Precio*: {price}"
    bot.send_message(chat_id="TU_CHAT_ID", text=message, parse_mode=telegram.ParseMode.MARKDOWN)

### 📌 NOTIFICAR CUANDO SE CIERRA UNA OPERACIÓN ###
def notify_trade_close(symbol, profit, result):
    message = f"✅ *Operación cerrada*\n\n" \
              f"📌 *Par*: {symbol}\n" \
              f"💵 *Profit*: {profit} USD\n" \
              f"📊 *Resultado*: {result}"
    bot.send_message(chat_id="TU_CHAT_ID", text=message, parse_mode=telegram.ParseMode.MARKDOWN)

### 📌 ABRIR OPERACIONES ###
def place_orders(update, context):
    global open_trades
    if len(open_trades) >= max_open_trades:
        context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Límite de operaciones abiertas alcanzado.")
        return

    for symbol in symbols:
        action = trading_strategy(symbol)
        if action == "hold":
            continue

        sl, tp = calculate_sl_tp(symbol)
        order_type = mt5.ORDER_TYPE_BUY if action == "buy" else mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).ask if action == "buy" else mt5.symbol_info_tick(symbol).bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": price - sl if action == "buy" else price + sl,
            "tp": price + tp if action == "buy" else price - tp,
            "deviation": 5,
            "magic": 123456,
            "comment": "Trading Bot AI",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            cursor.execute("INSERT INTO trades (symbol, action, lot, sl, tp, profit) VALUES (?, ?, ?, ?, ?, ?)", 
                           (symbol, action, lot_size, sl, tp, 0))
            conn.commit()
            open_trades.append(result.order)
            notify_trade_open(symbol, action, lot_size, sl, tp, price)  # Notificar apertura
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ Orden {action} enviada para {symbol}.")
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"⚠️ Error al enviar orden para {symbol}.")

### 📌 MONITOREAR OPERACIONES ABIERTAS ###
def check_open_trades(update, context):
    trades = mt5.positions_get()
    if not trades:
        context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ No hay operaciones abiertas.")
        return

    message = "🔹 *Operaciones abiertas:*\n\n"
    for trade in trades:
        message += f"📌 *Par*: {trade.symbol}\n" \
                   f"🔹 *Acción*: {'BUY' if trade.type == 0 else 'SELL'}\n" \
                   f"💰 *Precio*: {trade.price_open}\n" \
                   f"📉 *Stop Loss*: {trade.sl}\n" \
                   f"📈 *Take Profit*: {trade.tp}\n" \
                   f"💵 *Profit actual*: {trade.profit}\n\n"
    context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode=telegram.ParseMode.MARKDOWN)

### 📌 OBTENER HISTORIAL DE OPERACIONES ###
def get_trade_history(update, context):
    cursor.execute("SELECT symbol, action, profit FROM trades ORDER BY open_time DESC LIMIT 10")
    trades = cursor.fetchall()
    
    if not trades:
        context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ No hay historial de operaciones.")
        return

    message = "📜 *Últimas 10 operaciones:*\n\n"
    for trade in trades:
        message += f"📌 *Par*: {trade[0]}\n" \
                   f"🔹 *Acción*: {trade[1].upper()}\n" \
                   f"💵 *Profit*: {trade[2]} USD\n\n"
    context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode=telegram.ParseMode.MARKDOWN)

### 📌 COMANDOS TELEGRAM ###
dispatcher.add_handler(CommandHandler('trade', place_orders))
dispatcher.add_handler(CommandHandler('open_trades', check_open_trades))
dispatcher.add_handler(CommandHandler('trade_history', get_trade_history))

updater.start_polling()

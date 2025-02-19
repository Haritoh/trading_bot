import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import sqlite3
import os
import telebot
from sklearn.linear_model import LinearRegression
from time import sleep
from threading import Thread

# 🔹 Cargar credenciales desde variables de entorno (GitHub Secrets)
MT5_LOGIN = os.getenv("MT5_LOGIN")
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 🔹 Conectar con MetaTrader 5
def connect_mt5():
    if mt5.initialize(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER):
        print("✅ Conectado a MetaTrader 5")
    else:
        print("❌ Error al conectar a MetaTrader 5:", mt5.last_error())

# 🔹 Configurar Telegram
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# 🔹 Base de Datos para registro de operaciones
conn = sqlite3.connect("trading_history.db")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        order_type TEXT,
        volume REAL,
        open_price REAL,
        close_price REAL,
        profit REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()

# 🔹 Parámetros de Trading
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
LOT_SIZE = 0.1  # Tamaño del lote
MAX_OPEN_TRADES = 5  # Límite de operaciones abiertas
RISK_PER_TRADE = 0.02  # 2% del capital
STOP_LOSS_PIPS = 20
TAKE_PROFIT_PIPS = 40

# 🔹 Función para obtener datos del mercado
def get_market_data(symbol, n=100):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, n)
    df = pd.DataFrame(rates)
    df['close_change'] = df['close'].pct_change()
    return df.dropna()

# 🔹 Modelo de IA (Regresión Lineal)
def train_model(symbol):
    data = get_market_data(symbol)
    X = np.array(range(len(data))).reshape(-1, 1)
    y = data['close'].values
    model = LinearRegression().fit(X, y)
    return model.predict([[len(data)]])[0]

# 🔹 Función para calcular Stop Loss y Take Profit dinámicos
def calculate_sl_tp(price, direction):
    if direction == "buy":
        stop_loss = price - (STOP_LOSS_PIPS * 0.0001)
        take_profit = price + (TAKE_PROFIT_PIPS * 0.0001)
    else:
        stop_loss = price + (STOP_LOSS_PIPS * 0.0001)
        take_profit = price - (TAKE_PROFIT_PIPS * 0.0001)
    return stop_loss, take_profit

# 🔹 Función para abrir operaciones
def open_trade(symbol, order_type):
    if len(mt5.positions_get()) >= MAX_OPEN_TRADES:
        print("Límite de operaciones abiertas alcanzado.")
        return

    price = mt5.symbol_info_tick(symbol).ask if order_type == "buy" else mt5.symbol_info_tick(symbol).bid
    stop_loss, take_profit = calculate_sl_tp(price, order_type)
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": LOT_SIZE,
        "type": mt5.ORDER_TYPE_BUY if order_type == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": stop_loss,
        "tp": take_profit,
        "magic": 1001,
        "comment": "AI Trading Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    order = mt5.order_send(request)
    
    if order.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ Orden {order_type.upper()} abierta en {symbol}")
        bot.send_message(TELEGRAM_CHAT_ID, f"✅ {symbol} - {order_type.upper()} abierta a {price}\n🎯 TP: {take_profit} | 🛑 SL: {stop_loss}")
    else:
        print(f"❌ Error al abrir operación en {symbol}: {order.comment}")
        bot.send_message(TELEGRAM_CHAT_ID, f"❌ Error al abrir operación en {symbol}: {order.comment}")

# 🔹 Función para cerrar operaciones abiertas
def close_trades():
    open_positions = mt5.positions_get()
    if open_positions:
        for pos in open_positions:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket,
                "price": mt5.symbol_info_tick(pos.symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(pos.symbol).ask,
                "magic": 1001,
                "comment": "Cierre automático AI Bot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            order = mt5.order_send(request)
            if order.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"✅ Operación cerrada en {pos.symbol} con profit de {pos.profit}")
                bot.send_message(TELEGRAM_CHAT_ID, f"📉 {pos.symbol} - Operación cerrada con profit de {pos.profit}")
                
                # Guardar en la base de datos
                cursor.execute("INSERT INTO trades (symbol, order_type, volume, open_price, close_price, profit) VALUES (?, ?, ?, ?, ?, ?)",
                               (pos.symbol, "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL", pos.volume, pos.price_open, pos.price_current, pos.profit))
                conn.commit()

# 🔹 Comandos de Telegram
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🚀 Bot de Trading Iniciado. Usa /help para ver los comandos disponibles.")

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "💡 Ayuda del Bot de Trading:\n\n"
        "/start - Inicia el bot.\n"
        "/login - Conecta a MetaTrader 5.\n"
        "/stop - Detiene el bot.\n"
        "/status - Muestra operaciones abiertas.\n"
        "/set_lot X - Cambia el tamaño del lote (X es el nuevo tamaño).\n"
        "/set_limit X - Cambia el límite de operaciones abiertas (X es el nuevo límite).\n"
        "/history - Muestra el historial de operaciones.\n"
    )
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['login'])
def login(message):
    connect_mt5()
    bot.reply_to(message, "✅ Intentando conectar a MetaTrader 5...")

@bot.message_handler(commands=['stop'])
def stop(message):
    bot.reply_to(message, "🛑 Deteniendo el bot. No se realizarán más operaciones.")
    exit()

@bot.message_handler(commands=['status'])
def status(message):
    positions = mt5.positions_get()
    if positions:
        status_message = "📊 Operaciones Abiertas:\n"
        for pos in positions:
            status_message += f"{pos.symbol}: {pos.type} - {pos.volume} lots\n"
    else:
        status_message = "🔍 No hay operaciones abiertas."
    bot.reply_to(message, status_message)

@bot.message_handler(commands=['set_lot'])
def set_lot(message):
    global LOT_SIZE
    try:
        new_lot = float(message.text.split()[1])
        LOT_SIZE = new_lot
        bot.reply_to(message, f"Tamaño del lote cambiado a: {LOT_SIZE}")
    except (IndexError, ValueError):
        bot.reply_to(message, "⚠️ Usa: /set_lot X (donde X es el nuevo tamaño del lote)")

@bot.message_handler(commands=['set_limit'])
def set_limit(message):
    global MAX_OPEN_TRADES
    try:
        new_limit = int(message.text.split()[1])
        MAX_OPEN_TRADES = new_limit
        bot.reply_to(message, f"Límite de operaciones abiertas cambiado a: {MAX_OPEN_TRADES}")
    except (IndexError, ValueError):
        bot.reply_to(message, "⚠️ Usa: /set_limit X (donde X es el nuevo límite de operaciones)")

@bot.message_handler(commands=['history'])
def history(message):
    cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC")
    trades = cursor.fetchall()
    if trades:
        history_message = "📜 Historial de Operaciones:\n"
        for trade in trades:
            history_message += f"ID: {trade[0]}, Símbolo: {trade[1]}, Tipo: {trade[2]}, Volumen: {trade[3]}, Precio de Apertura: {trade[4]}, Precio de Cierre: {trade[5]}, Profit: {trade[6]}, Fecha: {trade[7]}\n"
    else:
        history_message = "📭 No hay historial de operaciones."
    bot.reply_to(message, history_message)

# 🔹 Lógica principal del bot
def run_bot():
    print("🚀 Bot de Trading Iniciado...")
    bot.send_message(TELEGRAM_CHAT_ID, "🚀 Bot de Trading Iniciado...")
    
    while True:
        for symbol in SYMBOLS:
            prediction = train_model(symbol)
            current_price = mt5.symbol_info_tick(symbol).bid

            if prediction > current_price:
                open_trade(symbol, "buy")
            elif prediction < current_price:
                open_trade(symbol, "sell")

        close_trades()
        sleep(1800)  # Esperar 30 minutos antes de la siguiente ejecución

# 🔹 Ejecutar el bot
if __name__ == "__main__":
    run_bot_thread = Thread(target=run_bot)
    run_bot_thread.start()
    bot.polling()

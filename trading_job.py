from backtesting.test import SMA
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import yfinance as yf
import pandas_ta as ta
import pyotp
import pandas as pd
import numpy as np
import time
from datetime import datetime
from logzero import logger
import login as l
import requests

def send_telegram_message(message):
    bot_token = '#ENTER YOUR TELEGRAM BOT TOKEN HERE'
    chat_id = '#ENTER YOUR TELEGRAM CHAT ID HERE'
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"Telegram error: {response.text}")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")


# SmartAPI login
obj = SmartConnect(api_key=l.api_key)
token = pyotp.TOTP(l.totp).now()
data = obj.generateSession(l.user_name, l.password, token)
refreshToken = data['data']['refreshToken']
feedToken = obj.getfeedToken()
l.feed_token = feedToken
userProfile = obj.getProfile(refreshToken)

print("Login Success:", userProfile)

# Order placement function
def place_order(symbol, token, qty, exch_seg, buy_sell, ordertype, price):
    try:
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": str(token),
            "transactiontype": buy_sell,
            "exchange": exch_seg,
            "ordertype": ordertype,
            "producttype": "DELIVERY",
            "duration": "DAY",
            "price": price,
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(qty)
        }
        response = obj.placeOrderFullResponse(orderparams)
        logger.info(f"PlaceOrder Full Response : {response}")
    except Exception as e:
        logger.exception(f"Order placement failed: {e}")

# Fetch historical data
def get_data(symbol: str, period='60d', interval='30m'):
    data = yf.download(tickers=symbol, period=period, interval=interval)
    data.reset_index(inplace=True)
    return data

# Technical indicator functions
def calculate_atr(data, period=14):
    data['ATR'] = ta.atr(data['High'], data['Low'], data['Close'], length=period)
    return data

# Indicators
def add_indicators(data):
    data['RSI'] = ta.rsi(data['Close'], length=14)
    data['MACD'] = data['Close'].ewm(span=12, adjust=False).mean() - data['Close'].ewm(span=26, adjust=False).mean()
    data['Signal_Line'] = data['MACD'].ewm(span=9, adjust=False).mean()
    adx = ta.adx(data['High'], data['Low'], data['Close'], length=14)
    data['ADX'] = adx['ADX_14']
    data['DI+'] = adx['DMP_14']
    data['DI-'] = adx['DMN_14']
    data['EMA_50'] = ta.ema(data['Close'], length=50)
    return data


def identify_rejection(data):
    data['rejection'] = data.apply(lambda row:
        2 if ((min(row['Open'], row['Close']) - row['Low']) > 0.7 * abs(row['Close'] - row['Open']) and
              (row['High'] - max(row['Close'], row['Open'])) < 1.5 * abs(row['Close'] - row['Open']) and
              abs(row['Open'] - row['Close']) > row['ATR'] * 0.05)
        else 1 if ((row['High'] - max(row['Open'], row['Close'])) > 0.7 * abs(row['Open'] - row['Close']) and
                  (min(row['Close'], row['Open']) - row['Low']) < 1.5 * abs(row['Open'] - row['Close']) and
                  abs(row['Open'] - row['Close']) > row['ATR'] * 0.05)
        else 0, axis=1)
    return data

def calculate_pivot_points(data):
    data['Pivot'] = (data['High'] + data['Low'] + data['Close']) / 3
    data['Resistance_1'] = (2 * data['Pivot']) - data['Low']
    data['Support_1'] = (2 * data['Pivot']) - data['High']
    return data

def generate_signals(data):
    data['signal'] = np.where(
        (data['rejection'] == 2) &
        (data['Low'] <= data['Support_1']) &
        (data['RSI'] < 60) &
        (data['Close'] > data['EMA_50']),
        2,
        np.where(
            (data['rejection'] == 1) &
            (data['High'] >= data['Resistance_1']) &
            (data['RSI'] > 40) &
            (data['Close'] < data['EMA_50']),
            1, 0
        )
    )
    return data

# Real-time loop
symbol = 'VIKASECO.NS'
symbol_token = 25756  # Replace this with dynamic token mapping if needed
tradingsymbol = 'VIKASECO-EQ'

last_signal_time = None

while True:
    try:
        data = get_data(symbol)
        data.columns = [col[0] if col[1] == symbol else col[0] for col in data.columns]
        if data is None or data.empty:
            logger.error("Downloaded data is empty. Skipping this iteration.")
            time.sleep(60)
            continue
        logger.info("Data fetched successfully")

        data = calculate_atr(data)
        logger.info("ATR calculated")

        data = add_indicators(data)
        if data is None:
            time.sleep(60)
            continue

        data.dropna(inplace=True)

        data = identify_rejection(data)
        logger.info("Rejection candles identified")

        data = calculate_pivot_points(data)
        logger.info("Pivot points calculated")

        data = generate_signals(data)
        logger.info("Signals generated")

        # Check that signal column exists
        if 'signal' not in data.columns:
            logger.error("Signal column not found in DataFrame.")
            time.sleep(60)
            continue

        latest = data.iloc[-1]
        signal = latest['signal']
        bar_time = latest['Datetime'] if 'Datetime' in latest else latest['Date']

        if signal == 2 and bar_time != last_signal_time:
            place_order(tradingsymbol, symbol_token, 1, "NSE", "BUY", "LIMIT", price=round(latest['Close'], 2))
            last_signal_time = bar_time
            send_telegram_message(f"📈 BUY Signal for {symbol}")

        elif signal == 1 and bar_time != last_signal_time:
            place_order(tradingsymbol, symbol_token, 1, "NSE", "SELL", "LIMIT", price=round(latest['Close'], 2))
            last_signal_time = bar_time
            send_telegram_message(f"📉 SELL Signal for {symbol}")

        time.sleep(60)

    except Exception as e:
        logger.error(f"Error in real-time loop: {e}")
        time.sleep(60)
from backtesting.test import SMA
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import yfinance as yf
import pandas_ta as ta
import pyotp
import pandas as pd
import numpy as np
import time
from datetime import datetime
from logzero import logger
import login as l
import requests

def send_telegram_message(message):
    bot_token = '8121361483:AAFhmt3gtE3Zh3vFo75pjhL-lo-eGvN9GJo'
    chat_id = '1941510197'
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"Telegram error: {response.text}")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")


# SmartAPI login
obj = SmartConnect(api_key=l.api_key)
token = pyotp.TOTP(l.totp).now()
data = obj.generateSession(l.user_name, l.password, token)
refreshToken = data['data']['refreshToken']
feedToken = obj.getfeedToken()
l.feed_token = feedToken
userProfile = obj.getProfile(refreshToken)

print("Login Success:", userProfile)

# Order placement function
def place_order(symbol, token, qty, exch_seg, buy_sell, ordertype, price):
    try:
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": str(token),
            "transactiontype": buy_sell,
            "exchange": exch_seg,
            "ordertype": ordertype,
            "producttype": "DELIVERY",
            "duration": "DAY",
            "price": price,
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(qty)
        }
        response = obj.placeOrderFullResponse(orderparams)
        logger.info(f"PlaceOrder Full Response : {response}")
    except Exception as e:
        logger.exception(f"Order placement failed: {e}")

# Fetch historical data
def get_data(symbol: str, period='60d', interval='30m'):
    data = yf.download(tickers=symbol, period=period, interval=interval)
    data.reset_index(inplace=True)
    return data

# Technical indicator functions
def calculate_atr(data, period=14):
    data['ATR'] = ta.atr(data['High'], data['Low'], data['Close'], length=period)
    return data

# Indicators
def add_indicators(data):
    data['RSI'] = ta.rsi(data['Close'], length=14)
    data['MACD'] = data['Close'].ewm(span=12, adjust=False).mean() - data['Close'].ewm(span=26, adjust=False).mean()
    data['Signal_Line'] = data['MACD'].ewm(span=9, adjust=False).mean()
    adx = ta.adx(data['High'], data['Low'], data['Close'], length=14)
    data['ADX'] = adx['ADX_14']
    data['DI+'] = adx['DMP_14']
    data['DI-'] = adx['DMN_14']
    data['EMA_50'] = ta.ema(data['Close'], length=50)
    return data


def identify_rejection(data):
    data['rejection'] = data.apply(lambda row:
        2 if ((min(row['Open'], row['Close']) - row['Low']) > 0.7 * abs(row['Close'] - row['Open']) and
              (row['High'] - max(row['Close'], row['Open'])) < 1.5 * abs(row['Close'] - row['Open']) and
              abs(row['Open'] - row['Close']) > row['ATR'] * 0.05)
        else 1 if ((row['High'] - max(row['Open'], row['Close'])) > 0.7 * abs(row['Open'] - row['Close']) and
                  (min(row['Close'], row['Open']) - row['Low']) < 1.5 * abs(row['Open'] - row['Close']) and
                  abs(row['Open'] - row['Close']) > row['ATR'] * 0.05)
        else 0, axis=1)
    return data

def calculate_pivot_points(data):
    data['Pivot'] = (data['High'] + data['Low'] + data['Close']) / 3
    data['Resistance_1'] = (2 * data['Pivot']) - data['Low']
    data['Support_1'] = (2 * data['Pivot']) - data['High']
    return data

def generate_signals(data):
    data['signal'] = np.where(
        (data['rejection'] == 2) &
        (data['Low'] <= data['Support_1']) &
        (data['RSI'] < 60) &
        (data['Close'] > data['EMA_50']),
        2,
        np.where(
            (data['rejection'] == 1) &
            (data['High'] >= data['Resistance_1']) &
            (data['RSI'] > 40) &
            (data['Close'] < data['EMA_50']),
            1, 0
        )
    )
    return data

# Real-time loop
symbol = 'VIKASECO.NS'
symbol_token = 25756  # Replace this with dynamic token mapping if needed
tradingsymbol = 'VIKASECO-EQ'

last_signal_time = None

while True:
    try:
        data = get_data(symbol)
        data.columns = [col[0] if col[1] == symbol else col[0] for col in data.columns]
        if data is None or data.empty:
            logger.error("Downloaded data is empty. Skipping this iteration.")
            time.sleep(60)
            continue
        logger.info("Data fetched successfully")

        data = calculate_atr(data)
        logger.info("ATR calculated")

        data = add_indicators(data)
        if data is None:
            time.sleep(60)
            continue

        data.dropna(inplace=True)

        data = identify_rejection(data)
        logger.info("Rejection candles identified")

        data = calculate_pivot_points(data)
        logger.info("Pivot points calculated")

        data = generate_signals(data)
        logger.info("Signals generated")

        # Check that signal column exists
        if 'signal' not in data.columns:
            logger.error("Signal column not found in DataFrame.")
            time.sleep(60)
            continue

        latest = data.iloc[-1]
        signal = latest['signal']
        bar_time = latest['Datetime'] if 'Datetime' in latest else latest['Date']

        if signal == 2 and bar_time != last_signal_time:
            place_order(tradingsymbol, symbol_token, 1, "NSE", "BUY", "LIMIT", price=round(latest['Close'], 2))
            last_signal_time = bar_time
            send_telegram_message(f"📈 BUY Signal for {symbol}")

        elif signal == 1 and bar_time != last_signal_time:
            place_order(tradingsymbol, symbol_token, 1, "NSE", "SELL", "LIMIT", price=round(latest['Close'], 2))
            last_signal_time = bar_time
            send_telegram_message(f"📉 SELL Signal for {symbol}")

        time.sleep(60)

    except Exception as e:
        logger.error(f"Error in real-time loop: {e}")
        time.sleep(60)

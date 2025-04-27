import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objs as go
import time
import threading
import yfinance as yf
import pandas_ta as ta
from SmartApi import SmartConnect
import pyotp
import requests
import login as l
from datetime import datetime

# -------------------------------------------------
# Streamlit minimal black-and-white theme custom CSS
st.markdown(
    """
    <style>
    body {
        background-color: #000000;
        color: #FFFFFF;
    }
    .stButton>button {
        border-radius: 10px;
        padding: 0.5em 1em;
    }
    </style>
    """,
    unsafe_allow_html=True
)
if 'running' not in st.session_state:
    st.session_state['running'] = False

# -------------------------------------------------
# SmartAPI login
@st.cache_resource
def smartapi_login():
    obj = SmartConnect(api_key=l.api_key)
    token = pyotp.TOTP(l.totp).now()
    data = obj.generateSession(l.user_name, l.password, token)
    feedToken = obj.getfeedToken()
    userProfile = obj.getProfile(data['data']['refreshToken'])
    return obj, feedToken, userProfile

obj, feed_token, userProfile = smartapi_login()
st.success(f"Logged in as: {userProfile['data']['name']}")

# -------------------------------------------------
# Telegram Bot toggle
telegram_toggle = st.sidebar.checkbox('Send Telegram Notifications', value=True)

def send_telegram_message(message):
    if telegram_toggle:
        bot_token = 'YOUR_BOT_TOKEN'
        chat_id = 'YOUR_CHAT_ID'
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': message}
        try:
            response = requests.post(url, data=payload)
        except Exception as e:
            st.error(f"Telegram Error: {e}")

# -------------------------------------------------
# Order placement
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
        st.markdown(f"<h4 style='color: lime; animation: blink 1s infinite;'>✨ Order Placed: {buy_sell} {symbol} at {price}</h4>", unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Order Failed: {e}")

# Blinking animation
st.markdown("""
    <style>
    @keyframes blink {
        0% {opacity: 1;}
        50% {opacity: 0;}
        100% {opacity: 1;}
    }
    </style>
""", unsafe_allow_html=True)

# -------------------------------------------------
# Indicators
def add_indicators(data):
    data['ATR'] = ta.atr(data['High'], data['Low'], data['Close'], length=14)
    data['RSI'] = ta.rsi(data['Close'], length=14)
    data['EMA_50'] = ta.ema(data['Close'], length=50)
    macd_line = data['Close'].ewm(span=12, adjust=False).mean() - data['Close'].ewm(span=26, adjust=False).mean()
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    data['MACD'] = macd_line
    data['Signal_Line'] = signal_line
    adx = ta.adx(data['High'], data['Low'], data['Close'], length=14)
    data['ADX'] = adx['ADX_14']
    data['DI+'] = adx['DMP_14']
    data['DI-'] = adx['DMN_14']
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

# -------------------------------------------------
# Trading logic
signal_log = []

def start_trading(symbol, token, tradingsymbol, timeframe, qty, seg, ordertype):
    last_signal_time = None
    while st.session_state['running']:
        try:
            data = yf.download(tickers=symbol, period='60d', interval=timeframe)
            data.reset_index(inplace=True)
            if data.empty:
                st.error("No data fetched.")
                time.sleep(60)
                continue

            data = add_indicators(data)
            data = identify_rejection(data)
            data = calculate_pivot_points(data)
            data = generate_signals(data)
            data.dropna(inplace=True)

            latest = data.iloc[-1]
            signal = latest['signal']
            bar_time = latest['Datetime'] if 'Datetime' in latest else latest['Date']

            emote = "🔄"
            if signal == 2 and bar_time != last_signal_time:
                place_order(tradingsymbol, token, qty, seg, "BUY", ordertype, price=round(latest['Close'], 2))
                last_signal_time = bar_time
                signal_log.append((datetime.now().strftime("%H:%M:%S"), "BUY", round(latest['Close'],2)))
                send_telegram_message(f"📈 BUY Signal for {symbol}")
                emote = "📈"

            elif signal == 1 and bar_time != last_signal_time:
                place_order(tradingsymbol, token, qty, seg, "SELL", ordertype, price=round(latest['Close'], 2))
                last_signal_time = bar_time
                signal_log.append((datetime.now().strftime("%H:%M:%S"), "SELL", round(latest['Close'],2)))
                send_telegram_message(f"📉 SELL Signal for {symbol}")
                emote = "📉"

            # Update moving emotes
            st.session_state['emote'] = emote
            st.session_state['signal'] = "BUY" if signal == 2 else "SELL" if signal == 1 else "NO ACTION"
            st.session_state['last_signal_time'] = bar_time

            # Realtime Candlestick Chart
            fig = go.Figure(data=[go.Candlestick(
                x=data['Datetime'],
                open=data['Open'],
                high=data['High'],
                low=data['Low'],
                close=data['Close']
            )])
            fig.update_layout(title='Realtime Candlestick', template='plotly_white', xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

            time.sleep(60)

        except Exception as e:
            st.error(f"Error in Trading: {e}")
            time.sleep(60)

# -------------------------------------------------
# Streamlit UI
st.title("📈 STOCK SEER Dashboard")

col1, col2, col3 = st.columns(3)

with col1:
    symbol = st.text_input("Stock Symbol", value="VIKASECO.NS")

with col2:
    symbol_token = st.number_input("Symbol Token", value=25756)

with col3:
    tradingsymbol = st.text_input("Trading Symbol", value="VIKASECO-EQ")

timeframe = st.selectbox("Select Timeframe", ["15m", "30m", "1h"], index=1)
qty = st.number_input("Order Quantity", value=1)
seg = st.selectbox("Exchange Segment", ["NSE", "BSE"])
ordertype = st.selectbox("Order Type", ["LIMIT", "MARKET"])


start_col, stop_col = st.columns(2)

with start_col:
    if st.button("🟩 Start Trading"):
        if not st.session_state['running']:
            st.session_state['running'] = True
            threading.Thread(target=start_trading, args=(symbol, symbol_token, tradingsymbol, timeframe, qty, seg, ordertype)).start()
            st.success("Trading Started!")

with stop_col:
    if st.button("🟥 Stop Trading"):
        st.session_state['running'] = False
        st.warning("Trading Stopped!")

# Signal History Table
st.subheader("📜 Signal Log History")
if signal_log:
    log_df = pd.DataFrame(signal_log, columns=["Time", "Signal", "Price"])
    st.dataframe(log_df, use_container_width=True)

# Moving Emote
st.subheader(f"Current Signal: {st.session_state.get('signal', 'No Action')} {st.session_state.get('emote', '')}")

# Download CSV
if st.button("⬇️ Download Historical Data CSV"):
    hist_data = yf.download(symbol, period="60d", interval=timeframe)
    csv = hist_data.to_csv(index=False).encode('utf-8')
    st.download_button("Download CSV", csv, file_name=f"{symbol}_historical.csv", mime='text/csv')

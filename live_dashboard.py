# ============================================================
# SANJAY RANA - DELTA REAL TRADING DASHBOARD
# PART 1/4
# ============================================================

import os
import time
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# SETTINGS
# ============================================================

BASE_URL = os.getenv(
    "DELTA_BASE_URL",
    "https://api.india.delta.exchange"
).rstrip("/")

SYMBOL = os.getenv("DELTA_SYMBOL", "BTCUSD")
PRODUCT_ID = int(os.getenv("DELTA_PRODUCT_ID", "27"))

TIMEFRAME = "5m"
CANDLE_SECONDS = 300

ATR_PERIOD = 10
MULTIPLIER = 3.0

REFRESH_SECONDS = 5

# ============================================================
# REAL TRADING MASTER SWITCH
# ============================================================

REMOTE_TRADING = (
    os.getenv("REMOTE_TRADING", "false").lower() == "true"
)

# ============================================================
# DEFAULT REMOTE CONTROL SETTINGS
# ============================================================

DEFAULT_BUY_OFFSET = int(
    os.getenv("BUY_OFFSET", "-150")
)

DEFAULT_SELL_OFFSET = int(
    os.getenv("SELL_OFFSET", "150")
)

# ============================================================
# MASTER BTC QUANTITY — ONLY THIS VALUE NEEDS TO BE CHANGED
# 0.001 = 1 contract = 1 TP basket
# 0.010 = 10 contracts = 3 baskets: 0.005 / 0.003 / 0.002 BTC
# ============================================================
ORDER_QTY = float(
    os.getenv("ORDER_QTY", "0.001")
)

CONTRACT_BTC = 0.001

if ORDER_QTY <= 0:
    raise ValueError("ORDER_QTY must be greater than 0")

_total_contracts = ORDER_QTY / CONTRACT_BTC
if abs(_total_contracts - round(_total_contracts)) > 1e-9:
    raise ValueError("ORDER_QTY must be a multiple of 0.001 BTC")

DEFAULT_ORDER_SIZE = int(round(_total_contracts))

# LIMIT pending रहने के बाद कितने seconds में MARKET करना है.
# 0 = automatic MARKET conversion बंद.
DEFAULT_LIMIT_TIMEOUT = int(
    os.getenv("LIMIT_TIMEOUT", "60000000")
)

TARGET_1 = int(os.getenv("TARGET_1", "200"))
TARGET_2 = int(os.getenv("TARGET_2", "600"))
TARGET_3 = int(os.getenv("TARGET_3", "900"))


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Sanjay Rana Real Trading",
    page_icon="📈",
    layout="wide"
)

st.title("📈 SANJAY RANA — REAL TRADING DASHBOARD")

st.caption(
    "5 Minute | ATR 10 | Multiplier 3.0 | HL2 | "
    "Confirmed Candle Close"
)


# ============================================================
# INDIAN TIME
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))


def indian_time(timestamp):
    try:
        ts = int(float(timestamp))

        if ts > 10_000_000_000:
            ts = ts // 1000

        return datetime.fromtimestamp(
            ts,
            tz=timezone.utc
        ).astimezone(IST).strftime(
            "%Y-%m-%d %H:%M:%S IST"
        )

    except Exception:
        return "-"


# ============================================================
# DISPLAY HELPERS
# ============================================================

def number(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def show_price(value):
    value = number(value)

    if value is None:
        return "-"

    return f"{value:,.2f}"


# ============================================================
# DELTA API
# ============================================================

class DeltaAPI:

    def __init__(self, api_key=None, api_secret=None):
        global API_KEY, API_SECRET
        
        if api_key:
            API_KEY = api_key
        if api_secret:
            API_SECRET = api_secret

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": "Sanjay-Rana-Real-Trading-Bot",
            "Accept": "application/json"
        })
        



    # --------------------------------------------------------
    # HMAC SIGNATURE
    # --------------------------------------------------------

    def make_signature(
        self,
        method,
        timestamp,
        path,
        query_string="",
        body=""
    ):

        message = (
            method.upper()
            + timestamp
            + path
            + query_string
            + body
        )

        return hmac.new(
            API_SECRET.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()


    # --------------------------------------------------------
    # REQUEST
    # --------------------------------------------------------

    def request(
        self,
        method,
        path,
        params=None,
        body=None,
        private=False
    ):

        params = params or {}

        body = body or {}

        payload = ""

        if body:
            payload = json.dumps(
                body,
                separators=(",", ":")
            )

        query_string = ""

        if params:

            parts = []

            for key, value in params.items():

                parts.append(
                    f"{key}={value}"
                )

            query_string = "?" + "&".join(parts)


        headers = {
            "Accept": "application/json",
            "User-Agent": "Sanjay-Rana-Real-Trading-Bot"
        }


        if private:

            if not API_KEY or not API_SECRET:

                return {
                    "success": False,
                    "error": "API key/secret missing"
                }


            timestamp = str(
                int(time.time())
            )


            signature = self.make_signature(
                method,
                timestamp,
                path,
                query_string,
                payload
            )


            headers.update({
                "api-key": API_KEY,
                "timestamp": timestamp,
                "signature": signature,
                "Content-Type": "application/json"
            })


        try:

            response = self.session.request(
                method.upper(),
                BASE_URL + path,
                params=params,
                data=payload if payload else None,
                headers=headers,
                timeout=15
            )


            try:
                data = response.json()

            except Exception:

                return {
                    "success": False,
                    "error": response.text
                }


            return data


        except Exception as e:

            return {
                "success": False,
                "error": str(e)
            }


    # --------------------------------------------------------
    # PUBLIC
    # --------------------------------------------------------

    def candles(self):

        end = int(time.time())

        start = (
            end
            - (500 * CANDLE_SECONDS)
        )

        return self.request(
            "GET",
            "/v2/history/candles",
            params={
                "symbol": SYMBOL,
                "resolution": TIMEFRAME,
                "start": start,
                "end": end
            }
        )


    def ticker(self):

        return self.request(
            "GET",
            f"/v2/tickers/{SYMBOL}"
        )


    # --------------------------------------------------------
    # PRIVATE
    # --------------------------------------------------------

    def open_orders(self):

        return self.request(
            "GET",
            "/v2/orders",
            params={
                "product_id": PRODUCT_ID,
                "state": "open"
            },
            private=True
        )


    def closed_orders(self):

        return self.request(
            "GET",
            "/v2/orders",
            params={
                "product_id": PRODUCT_ID,
                "state": "closed"
            },
            private=True
        )


    def position(self):

        return self.request(
            "GET",
            "/v2/positions",
            params={
                "product_id": PRODUCT_ID
            },
            private=True
        )


    # --------------------------------------------------------
    # PLACE LIMIT ORDER
    # --------------------------------------------------------

    def place_limit_order(
        self,
        side,
        size,
        limit_price,
        take_profit_price=None,
        client_order_id=None
    ):

        body = {

            "product_id": PRODUCT_ID,

            "product_symbol": SYMBOL,

            "limit_price": str(
                limit_price
            ),

            "size": int(size),

            "side": side,

            "order_type": "limit_order",

            "time_in_force": "gtc",

            "post_only": False,

            "reduce_only": False
        }

        # Delta supports a bracket take-profit attached directly to a
        # new LIMIT order. This keeps TP visible with the pending entry
        # instead of waiting for a separate TP order after the fill.
        if take_profit_price is not None:
            body["bracket_take_profit_price"] = str(
                take_profit_price
            )
            body["bracket_take_profit_limit_price"] = str(
                take_profit_price
            )
            body["bracket_stop_trigger_method"] = (
                "last_traded_price"
            )

        if client_order_id:
            body["client_order_id"] = str(
                client_order_id
            )

        return self.request(
            "POST",
            "/v2/orders",
            body=body,
            private=True
        )


    # --------------------------------------------------------
    # CANCEL ORDER
    # --------------------------------------------------------

    def cancel_order(self, order_id):

        return self.request(
            "DELETE",
            f"/v2/orders/{order_id}",
            private=True
        )


# ============================================================
# API CREDENTIALS (OWNER & MEMBERS FROM GITHUB SECRETS)
# ============================================================
# यह कोड GitHub Secrets से कीज़ खुद ले लेता है
OWNER_KEY = st.secrets.get("OWNER_API_KEY", "")
OWNER_SECRET = st.secrets.get("OWNER_API_SECRET", "")

MEMBER1_KEY = st.secrets.get("MEMBER1_API_KEY", "")
MEMBER1_SECRET = st.secrets.get("MEMBER1_API_SECRET", "")



API_KEY = OWNER_KEY
API_SECRET = OWNER_SECRET

api = DeltaAPI()



# ============================================================
# BASIC STATUS (PERMANENTLY LIVE)
# ============================================================

st.info(
    "⚡ LIVE TRADING MODE: PERMANENTLY ACTIVE"
)

    # ============================================================
# OWNER API + MEMBER API CONTROL
# PLACE THIS DIRECTLY BELOW PART 1
# ============================================================

st.divider()

# ============================================================
# OWNER API
# ============================================================

st.header("👑 OWNER API")

# Credentials are loaded automatically from environment / GitHub Secrets
# ============================================================
# OWNER API CREDENTIALS (SECURE FETCH)
# ============================================================
try:
    OWNER_API_KEY = st.secrets.get("OWNER_API_KEY", os.getenv("OWNER_API_KEY", ""))
    OWNER_API_SECRET = st.secrets.get("OWNER_API_SECRET", os.getenv("OWNER_API_SECRET", ""))
except Exception:
    OWNER_API_KEY = os.getenv("OWNER_API_KEY", "")
    OWNER_API_SECRET = os.getenv("OWNER_API_SECRET", "")
    

# ============================================================
# OWNER STATUS (AUTOMATIC HEALTH CHECK)
# ============================================================

if not OWNER_API_KEY or not OWNER_API_SECRET:
    st.error("❌ OWNER_API_KEY / OWNER_API_SECRET GitHub Secrets में नहीं मिले।")
    st.session_state["owner_api_connected"] = False
else:
    try:
        owner_client = DeltaAPI(OWNER_API_KEY, OWNER_API_SECRET)
        owner_result = owner_client.position()
        
        if owner_result.get("success"):
            st.success("👑 Owner Status: CONNECTED & LIVE 🟢")
            st.session_state["owner_api_connected"] = True
            st.session_state["owner_api_key"] = OWNER_API_KEY
            st.session_state["owner_api_secret"] = OWNER_API_SECRET
        else:
            st.session_state["owner_api_connected"] = False
            err_text = str(owner_result.get("error", ""))
            
            if "ip" in err_text.lower() or "whitelist" in err_text.lower():
                st.error(f"🌐 IP WHITELIST ERROR: Streamlit Cloud का IP Delta Exchange पर जोड़ा नहीं है! | Details: {err_text}")
            else:
                st.error(f"🔴 Owner Status: NOT CONNECTED | Reason: {err_text}")
                
    except Exception as e:
        st.session_state["owner_api_connected"] = False
        st.error(f"❌ Owner API Connection Error: {e}")



# ============================================================
# FIXED 5 MEMBERS PRE-CONFIGURED (AUTOMATIC HEALTH CHECK)
# ============================================================

st.divider()
st.header("👥 MEMBER API CONTROL (5 MEMBERS)")

# 5 फिक्स मेंबर्स सीधे GitHub Secrets से लोड होंगे
st.session_state["members"] = [
    {
        "name": "Member 1",
        "api_key": st.secrets.get("MEMBER1_API_KEY", os.getenv("MEMBER1_API_KEY", "")),
        "api_secret": st.secrets.get("MEMBER1_API_SECRET", os.getenv("MEMBER1_API_SECRET", "")),
        "connected": False,
        "active": True
    },
    {
        "name": "Member 2",
        "api_key": st.secrets.get("MEMBER2_API_KEY", os.getenv("MEMBER2_API_KEY", "")),
        "api_secret": st.secrets.get("MEMBER2_API_SECRET", os.getenv("MEMBER2_API_SECRET", "")),
        "connected": False,
        "active": True
    },
    {
        "name": "Member 3",
        "api_key": st.secrets.get("MEMBER3_API_KEY", os.getenv("MEMBER3_API_KEY", "")),
        "api_secret": st.secrets.get("MEMBER3_API_SECRET", os.getenv("MEMBER3_API_SECRET", "")),
        "connected": False,
        "active": True
    },
    {
        "name": "Member 4",
        "api_key": st.secrets.get("MEMBER4_API_KEY", os.getenv("MEMBER4_API_KEY", "")),
        "api_secret": st.secrets.get("MEMBER4_API_SECRET", os.getenv("MEMBER4_API_SECRET", "")),
        "connected": False,
        "active": True
    },
    {
        "name": "Member 5",
        "api_key": st.secrets.get("MEMBER5_API_KEY", os.getenv("MEMBER5_API_KEY", "")),
        "api_secret": st.secrets.get("MEMBER5_API_SECRET", os.getenv("MEMBER5_API_SECRET", "")),
        "connected": False,
        "active": True
    }
]

st.info("👥 Total Pre-configured Members: 5 (Automatic Live Sync Enabled)")

# पांचों मेंबर्स का ऑटोमैटिक हेल्थ चेक लूप (बिना किसी बटन के)
for index, member in enumerate(st.session_state["members"]):
    st.markdown("---")
    st.subheader(f"👤 {member['name']}")

    if not member["api_key"] or not member["api_secret"]:
        member["connected"] = False
        st.error(f"❌ {member['name']}: GitHub Secrets में API Key या Secret गायब है (`MEMBER{index+1}_API_KEY`).")
    else:
        try:
            member_client = DeltaAPI(member["api_key"], member["api_secret"])
            member_result = member_client.position()
            
            if member_result.get("success"):
                member["connected"] = True
                st.success(f"🟢 {member['name']} — API CONNECTED & LIVE")
            else:
                member["connected"] = False
                err_text = str(member_result.get("error", ""))
                
                if "ip" in err_text.lower() or "whitelist" in err_text.lower():
                    st.error(f"🌐 IP WHITELIST ERROR ({member['name']}): Streamlit IP Delta पर जोड़ी नहीं है! | {err_text}")
                else:
                    st.error(f"🔴 {member['name']} — NOT CONNECTED | Reason: {err_text}")
                    
        except Exception as e:
        #   member["connected"] = False
            st.error(f"❌ {member['name']} API Error: {e}")

    if member["connected"]:
        st.write(f"Status: **REAL TRADING ACTIVE (AUTO)** 🚀")
    else:
        st.write(f"Status: **TRADING PAUSED (Check Secrets / IP)** ⚠️")


# ============================================================
# ACTIVE MEMBER SUMMARY TABLE
# ============================================================

st.divider()
st.subheader("📊 MEMBER SUMMARY")

summary = []
for member in st.session_state["members"]:
    summary.append({
        "Member": member["name"],
        "API": "CONNECTED" if member["connected"] else "NOT CONNECTED",
        "Trading": "ACTIVE" if member["active"] else "OFF"
    })

st.dataframe(
    pd.DataFrame(summary),
    use_container_width=True,
    hide_index=True
)



# ============================================================
# END — OWNER + MEMBER API BLOCK
#
# PART 2 इसके नीचे आएगा।
# PART 3 इसके बाद।
# PART 4 सबसे बाद।
#
# FINAL st.rerun() पूरी file के बिल्कुल अंत में रहेगा।
# ============================================================
# ============================================================
# PART 2/4
# CANDLE DATA + SUPERTREND ENGINE
# ============================================================

def get_result(data):

    if not data:
        return None

    if not data.get("success"):
        return None

    return data.get("result")


def make_dataframe(data):

    result = get_result(data)

    if not isinstance(result, list):
        return pd.DataFrame()

    rows = []

    for candle in result:
        try:
            rows.append({
                "time": int(candle["time"]),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle.get("volume", 0))
            })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    df = (
        df
        .drop_duplicates("time")
        .sort_values("time")
        .reset_index(drop=True)
    )

    return df


# ============================================================
# GET CANDLES
# ============================================================

candle_response = api.candles()

df = make_dataframe(candle_response)

if df.empty:
    st.error("Delta se candle data nahi mila.")
    st.stop()


# ============================================================
# ONLY COMPLETED 5-MINUTE CANDLES
# ============================================================

current_candle_start = (
    int(time.time()) // CANDLE_SECONDS
) * CANDLE_SECONDS

df = df[
    df["time"] < current_candle_start
].copy()

df = df.reset_index(drop=True)

if len(df) < ATR_PERIOD + 5:
    st.error("SuperTrend ke liye enough candles nahi hain.")
    st.stop()


# ============================================================
# ============================================================
# STANDARD TRADINGVIEW SUPERTREND 10,3 ENGINE
# ============================================================
# Reference chart: regular Delta BTCUSD 5-minute candles,
# SuperTrend 10 3, Source = HL2.
#
# This is NOT Heikin-Ashi.
# ATR = TradingView-style Wilder/RMA.
# Only completed 5-minute Delta candles reach this engine.
# ============================================================

prev_close = df["close"].shift(1)

tr1 = df["high"] - df["low"]
tr2 = (df["high"] - prev_close).abs()
tr3 = (df["low"] - prev_close).abs()
df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

df["ATR"] = float("nan")

if len(df) >= ATR_PERIOD:
    df.loc[ATR_PERIOD - 1, "ATR"] = (
        df["TR"].iloc[:ATR_PERIOD].mean()
    )

    for i in range(ATR_PERIOD, len(df)):
        df.loc[i, "ATR"] = (
            df.loc[i - 1, "ATR"] * (ATR_PERIOD - 1)
            + df.loc[i, "TR"]
        ) / ATR_PERIOD

df["HL2"] = (df["high"] + df["low"]) / 2.0

df["BASIC_UPPER"] = float("nan")
df["BASIC_LOWER"] = float("nan")
df["FINAL_UPPER"] = float("nan")
df["FINAL_LOWER"] = float("nan")
df["SUPERTREND"] = float("nan")
df["ST_DIRECTION"] = 0
df["SIGNAL"] = ""

prev_final_upper = None
prev_final_lower = None
prev_supertrend = None
prev_direction = 1

for i in range(len(df)):
    atr = df.loc[i, "ATR"]

    if pd.isna(atr):
        continue

    hl2 = float(df.loc[i, "HL2"])
    close = float(df.loc[i, "close"])

    basic_upper = hl2 + MULTIPLIER * float(atr)
    basic_lower = hl2 - MULTIPLIER * float(atr)

    df.loc[i, "BASIC_UPPER"] = basic_upper
    df.loc[i, "BASIC_LOWER"] = basic_lower

    if i == ATR_PERIOD - 1 or prev_final_upper is None:
        final_upper = basic_upper
        final_lower = basic_lower
    else:
        previous_close = float(df.loc[i - 1, "close"])

        if (
            basic_upper < prev_final_upper
            or previous_close > prev_final_upper
        ):
            final_upper = basic_upper
        else:
            final_upper = prev_final_upper

        if (
            basic_lower > prev_final_lower
            or previous_close < prev_final_lower
        ):
            final_lower = basic_lower
        else:
            final_lower = prev_final_lower

    df.loc[i, "FINAL_UPPER"] = final_upper
    df.loc[i, "FINAL_LOWER"] = final_lower

    if i == ATR_PERIOD - 1 or prev_supertrend is None:
        direction = 1
        supertrend = final_upper
    else:
        if prev_supertrend == prev_final_upper:
            if close <= final_upper:
                direction = 1
                supertrend = final_upper
            else:
                direction = -1
                supertrend = final_lower
        else:
            if close >= final_lower:
                direction = -1
                supertrend = final_lower
            else:
                direction = 1
                supertrend = final_upper

    df.loc[i, "ST_DIRECTION"] = direction
    df.loc[i, "SUPERTREND"] = supertrend

    if i > 0 and prev_direction != direction:
        if direction == -1:
            df.loc[i, "SIGNAL"] = "BUY"
        elif direction == 1:
            df.loc[i, "SIGNAL"] = "SELL"

    prev_final_upper = final_upper
    prev_final_lower = final_lower
    prev_supertrend = supertrend
    prev_direction = direction

# Compatibility with the existing dashboard.
df["M_TREND"] = df["ST_DIRECTION"]


# ============================================================
# SIGNAL HISTORY
# ============================================================


# ============================================================

signal_rows = df[
    df["SIGNAL"].isin(
        ["BUY", "SELL"]
    )
].copy()


# ============================================================
# CURRENT CANDLE
# ============================================================

last_candle = df.iloc[-1]

current_trend = int(
    last_candle["M_TREND"]
)

current_close = float(
    last_candle["close"]
)

current_supertrend = float(
    last_candle["SUPERTREND"]
)

current_signal = str(
    last_candle["SIGNAL"]
)


# ============================================================
# CURRENT DIRECTION
# ============================================================

if current_trend == -1:

    current_direction = "BUY / BULLISH 🟢"

else:

    current_direction = "SELL / BEARISH 🔴"


# ============================================================
# CURRENT ENTRY
# ============================================================

if len(signal_rows) >= 1:

    current_entry = signal_rows.iloc[-1]

    signal_direction = str(
        current_entry["SIGNAL"]
    )

    signal_entry_price = float(
        current_entry["close"]
    )

    signal_supertrend = float(
        current_entry["SUPERTREND"]
    )

    signal_time = indian_time(
        current_entry["time"]
    )

else:

    signal_direction = ""

    signal_entry_price = current_close

    signal_supertrend = current_supertrend

    signal_time = indian_time(
        last_candle["time"]
    )


# ============================================================
# PREVIOUS ENTRY
# ============================================================

if len(signal_rows) >= 2:

    previous_entry = signal_rows.iloc[-2]

    previous_entry_signal = str(
        previous_entry["SIGNAL"]
    )

    previous_entry_price = float(
        previous_entry["close"]
    )

    previous_entry_st = float(
        previous_entry["SUPERTREND"]
    )

    previous_entry_time = indian_time(
        previous_entry["time"]
    )

else:

    previous_entry_signal = ""

    previous_entry_price = None

    previous_entry_st = None

    previous_entry_time = "-"


# ============================================================
# DISPLAY
# ============================================================

st.divider()

st.header("📈 SUPERTREND — 5 MINUTE")

c1, c2, c3 = st.columns(3)

with c1:

    st.metric(
        "CURRENT DIRECTION",
        current_direction
    )

with c2:

    st.metric(
        "CURRENT CLOSE",
        show_price(current_close)
    )

with c3:

    st.metric(
        "SUPERTREND",
        show_price(current_supertrend)
    )


# ============================================================
# CURRENT ENTRY
# ============================================================

st.subheader("🎯 CURRENT ENTRY")

if signal_direction == "BUY":

    st.success(
        f"🟢 BUY | "
        f"ENTRY: {show_price(signal_entry_price)} | "
        f"SUPERTREND: {show_price(signal_supertrend)}"
    )

elif signal_direction == "SELL":

    st.error(
        f"🔴 SELL | "
        f"ENTRY: {show_price(signal_entry_price)} | "
        f"SUPERTREND: {show_price(signal_supertrend)}"
    )

else:

    st.info(
        "No confirmed SuperTrend entry."
    )


st.write(
    f"Signal Candle: **{signal_time}**"
)


# ============================================================
# PREVIOUS ENTRY
# ============================================================

st.subheader("📜 PREVIOUS ENTRY")

if previous_entry_signal == "BUY":

    st.success(
        f"🟢 BUY | "
        f"ENTRY: {show_price(previous_entry_price)} | "
        f"SUPERTREND: {show_price(previous_entry_st)}"
    )

elif previous_entry_signal == "SELL":

    st.error(
        f"🔴 SELL | "
        f"ENTRY: {show_price(previous_entry_price)} | "
        f"SUPERTREND: {show_price(previous_entry_st)}"
    )

else:

    st.info(
        "Previous entry available nahi hai."
    )


st.write(
    f"Signal Candle: **{previous_entry_time}**"
                                          )
# ============================================================
# PART 3/4
# REMOTE CONTROL + TARGETS + REAL LIMIT ORDER CONTROL
# ============================================================

st.divider()

st.header("🎛️ REMOTE CONTROL")


# ============================================================
# REAL TRADING PERMANENTLY ON (ALWAYS ACTIVE)
# ============================================================

if "remote_enabled" not in st.session_state:
    st.session_state["remote_enabled"] = True

if "last_order_signal" not in st.session_state:
    st.session_state["last_order_signal"] = ""

if "pending_order_id" not in st.session_state:
    st.session_state["pending_order_id"] = None

if "pending_order_side" not in st.session_state:
    st.session_state["pending_order_side"] = ""

if "pending_order_time" not in st.session_state:
    st.session_state["pending_order_time"] = 0

if "pending_basket_order_ids" not in st.session_state:
    st.session_state["pending_basket_order_ids"] = []

remote_enabled = True
st.session_state["remote_enabled"] = True

# प्रोफेशनल और मार्केट जैसा ब्लू स्टेटस बॉक्स
st.info("⚡ LIVE TRADING ENGINE: ACTIVE & PERMANENTLY ON")




# ============================================================
# ORDER SETTINGS
# ============================================================

r1, r2 = st.columns(2)


with r1:

    buy_offset = st.number_input(
        "BUY LIMIT OFFSET",
        value=DEFAULT_BUY_OFFSET,
        step=10,
        help="Example: -50 means signal price se 50 points neeche."
    )


with r2:

    sell_offset = st.number_input(
        "SELL LIMIT OFFSET",
        value=DEFAULT_SELL_OFFSET,
        step=10,
        help="Example: +50 means signal price se 50 points upar."
    )


r3, r4 = st.columns(2)


with r3:

    order_size = DEFAULT_ORDER_SIZE
    st.metric(
        "ORDER QTY",
        f"{ORDER_QTY:.3f} BTC"
    )
    st.caption(
        f"{order_size} contract(s) — quantity is controlled only by ORDER_QTY"
    )


with r4:

    limit_timeout = st.number_input(
        "LIMIT TIMEOUT (SECONDS)",
        min_value=0,
        value=DEFAULT_LIMIT_TIMEOUT,
        step=5,
        help="0 = MARKET conversion disabled."
    )


# ============================================================
# TARGET SETTINGS
# ============================================================

st.subheader("🎯 TARGET SETTINGS")


t1_points = st.number_input(
    "TARGET 1 POINTS",
    min_value=1,
    value=TARGET_1,
    step=50
)


t2_points = st.number_input(
    "TARGET 2 POINTS",
    min_value=1,
    value=TARGET_2,
    step=50
)


t3_points = st.number_input(
    "TARGET 3 POINTS",
    min_value=1,
    value=TARGET_3,
    step=50
)


# ============================================================
# ENTRY PRICE WITH REMOTE OFFSET
# ============================================================

if signal_direction == "BUY":

    limit_entry_price = (
        signal_entry_price
        + float(buy_offset)
    )

elif signal_direction == "SELL":

    limit_entry_price = (
        signal_entry_price
        + float(sell_offset)
    )

else:

    limit_entry_price = (
        signal_entry_price
    )


# ============================================================
# TARGET CALCULATION
# ============================================================

if signal_direction == "BUY":

    target1 = (
        limit_entry_price
        + t1_points
    )

    target2 = (
        limit_entry_price
        + t2_points
    )

    target3 = (
        limit_entry_price
        + t3_points
    )

elif signal_direction == "SELL":

    target1 = (
        limit_entry_price
        - t1_points
    )

    target2 = (
        limit_entry_price
        - t2_points
    )

    target3 = (
        limit_entry_price
        - t3_points
    )

else:

    target1 = limit_entry_price + t1_points
    target2 = limit_entry_price + t2_points
    target3 = limit_entry_price + t3_points


# ============================================================
# TARGET BASKET ALLOCATION
# ============================================================
# Delta BTCUSD product 27 uses integer contract size.
# The dashboard therefore builds whole-contract baskets.
# 1 contract = 0.001 BTC for the configured BTCUSD product.
#
# 1 contract  -> TP1 only
# 2 contracts -> TP1 + TP2
# 3 contracts -> TP1 + TP2 + TP3
# 10 contracts -> 5 / 3 / 2 contracts = 50% / 30% / 20%
# For 4-9 contracts, whole-contract rounding is used while keeping
# every active basket at least 1 contract.
# ============================================================


def build_target_baskets(total_contracts):

    total_contracts = int(total_contracts)

    if total_contracts <= 0:
        return []

    if total_contracts == 1:
        return [("TP1", 1, target1)]

    if total_contracts == 2:
        return [
            ("TP1", 1, target1),
            ("TP2", 1, target2)
        ]

    if total_contracts == 3:
        return [
            ("TP1", 1, target1),
            ("TP2", 1, target2),
            ("TP3", 1, target3)
        ]

    if total_contracts >= 10:
        tp1_qty = int(total_contracts * 0.50)
        tp2_qty = int(total_contracts * 0.30)
        tp3_qty = total_contracts - tp1_qty - tp2_qty

        return [
            ("TP1", tp1_qty, target1),
            ("TP2", tp2_qty, target2),
            ("TP3", tp3_qty, target3)
        ]

    # 4-9 contracts: keep all three baskets active and distribute
    # the remaining contracts according to the requested 50/30/20
    # proportions as closely as integer contracts allow.
    raw = [
        total_contracts * 0.50,
        total_contracts * 0.30,
        total_contracts * 0.20
    ]

    qty = [max(1, int(x)) for x in raw]

    while sum(qty) > total_contracts:
        idx = max(
            range(3),
            key=lambda i: (qty[i] - raw[i], qty[i])
        )
        if qty[idx] > 1:
            qty[idx] -= 1
        else:
            break

    while sum(qty) < total_contracts:
        idx = max(
            range(3),
            key=lambda i: raw[i] - qty[i]
        )
        qty[idx] += 1

    targets = [target1, target2, target3]
    names = ["TP1", "TP2", "TP3"]

    return [
        (names[i], qty[i], targets[i])
        for i in range(3)
        if qty[i] > 0
    ]


target_baskets = build_target_baskets(
    DEFAULT_ORDER_SIZE
)


# ============================================================
# DISPLAY ENTRY + TARGETS
# ============================================================

st.subheader("📌 ORDER ENTRY + TARGETS")


ec1, ec2, ec3, ec4 = st.columns(4)


with ec1:

    st.metric(
        "LIMIT ENTRY",
        show_price(limit_entry_price)
    )


with ec2:

    st.metric(
        "TARGET 1",
        show_price(target1)
    )


with ec3:

    st.metric(
        "TARGET 2",
        show_price(target2)
    )


with ec4:

    st.metric(
        "TARGET 3",
        show_price(target3)
    )


# ============================================================
# DIRECTION CHANGE
# ============================================================

st.subheader(
    "🔄 PENDING ORDER AUTO-CANCEL"
)

st.info(
    "SuperTrend direction change hote hi "
    "opposite pending LIMIT order automatically cancel hoga."
)


# ============================================================
# GET OPEN ORDERS
# ============================================================

open_orders_response = api.open_orders()

# SAFETY: never treat an API failure as "no open orders".
open_orders_check_ok = bool(
    isinstance(open_orders_response, dict)
    and open_orders_response.get("success") is True
)

open_orders = get_result(
    open_orders_response
)

if not isinstance(open_orders, list):
    open_orders = []


# ============================================================
# FIND OUR PENDING ORDER
# ============================================================

pending_orders = []

# Closed-order history is used as a second layer of duplicate protection.
# A filled/cancelled order is no longer in /v2/orders state=open, so the
# current SuperTrend direction alone must never be allowed to create a
# duplicate after a Streamlit refresh/restart.
closed_orders_response = api.closed_orders()

closed_orders_check_ok = bool(
    isinstance(closed_orders_response, dict)
    and closed_orders_response.get("success") is True
)

closed_orders = get_result(closed_orders_response)

if not isinstance(closed_orders, list):
    closed_orders = []

for order in open_orders:

    try:

        order_product_id = int(
            order.get(
                "product_id",
                PRODUCT_ID
            )
        )

    except Exception:

        order_product_id = PRODUCT_ID


    if order_product_id != PRODUCT_ID:
        continue


    order_type = str(
        order.get(
            "order_type",
            order.get("type", "")
        )
    ).lower()


    state = str(
        order.get(
            "state",
            ""
        )
    ).lower()


    if (
        "limit" in order_type
        and state not in [
            "cancelled",
            "filled",
            "rejected"
        ]
    ):

        pending_orders.append(order)


# ============================================================
# CANCEL OLD OPPOSITE BASKETS ON SUPERTREND DIRECTION CHANGE
# ============================================================
# BUY signal  -> cancel old SELL entry + attached TP orders
# SELL signal -> cancel old BUY entry + attached TP orders
# After cancellation, refresh open orders before allowing a new entry.

cancel_failed = False
cancelled_order_ids = set()

if pending_orders and remote_enabled and signal_direction in ["BUY", "SELL"]:

    expected_new_side = (
        "buy" if signal_direction == "BUY" else "sell"
    )

    opposite_side = (
        "sell" if expected_new_side == "buy" else "buy"
    )

    for order in list(pending_orders):

        order_id = order.get("id")
        order_side = str(order.get("side", "")).lower()

        # Only cancel the old basket when its entry direction is
        # opposite to the NEW confirmed SuperTrend direction.
        if order_side != opposite_side or order_id is None:
            continue

        cancel_result = api.cancel_order(order_id)

        if (
            isinstance(cancel_result, dict)
            and cancel_result.get("success")
        ):
            cancelled_order_ids.add(str(order_id))

            st.warning(
                f"🔄 OLD {order_side.upper()} ENTRY CANCELLED — "
                f"SuperTrend changed to {signal_direction}. "
                f"Attached TP will no longer remain active."
            )

            if order_id == st.session_state.get(
                "pending_order_id"
            ):
                st.session_state["pending_order_id"] = None

        else:
            cancel_failed = True

            st.error(
                "🛑 OLD BASKET CANCEL FAILED — NEW ORDER BLOCKED. "
                + str(
                    cancel_result.get(
                        "error",
                        "Unknown error"
                    )
                    if isinstance(cancel_result, dict)
                    else cancel_result
                )
            )

    # IMPORTANT: never use the old open-order snapshot after cancelling.
    # Re-read Delta so the next order decision uses current exchange state.
    if not cancel_failed:

        refreshed_open_response = api.open_orders()

        refreshed_open_ok = bool(
            isinstance(refreshed_open_response, dict)
            and refreshed_open_response.get("success") is True
        )

        if not refreshed_open_ok:

            cancel_failed = True

            st.error(
                "🛑 CANCEL VERIFICATION FAILED — NEW ORDER BLOCKED. "
                "Delta open orders को दोबारा verify नहीं किया जा सका."
            )

        else:

            refreshed_open_orders = get_result(
                refreshed_open_response
            )

            if not isinstance(
                refreshed_open_orders,
                list
            ):
                refreshed_open_orders = []

            # If any opposite-side order is still open, never place
            # the new basket.
            for order in refreshed_open_orders:

                side = str(
                    order.get("side", "")
                ).lower()

                if side == opposite_side:

                    cancel_failed = True

                    st.error(
                        "🛑 OLD OPPOSITE ENTRY/TP ORDER IS STILL OPEN — "
                        "NEW ORDER BLOCKED FOR SAFETY."
                    )

                    break

            if not cancel_failed:

                # Use the refreshed exchange state for the rest of this run.
                open_orders = refreshed_open_orders

                pending_orders = [
                    order
                    for order in open_orders
                    if (
                        "limit"
                        in str(
                            order.get(
                                "order_type",
                                order.get("type", "")
                            )
                        ).lower()
                        and str(
                            order.get("state", "")
                        ).lower()
                        not in [
                            "cancelled",
                            "filled",
                            "rejected"
                        ]
                    )
                ]

# If cancellation could not be completed/verified, no new entry is allowed.


# ============================================================
# SHOW PENDING BASKETS + ATTACHED TARGETS
# ============================================================

if pending_orders:

    pending_rows = []

    for order in pending_orders:

        pending_rows.append({
            "Order ID": order.get("id", "-"),
            "Basket": order.get(
                "client_order_id",
                "-"
            ),
            "Side": str(
                order.get("side", "")
            ).upper(),
            "Entry LIMIT": show_price(
                order.get("limit_price")
            ),
            "Size (contracts)": order.get(
                "size",
                "-"
            ),
            "Size (BTC)": (
                f"{number(order.get('size'), 0) * CONTRACT_BTC:.3f}"
                if number(order.get("size")) is not None
                else "-"
            ),
            "Attached TP": show_price(
                order.get("bracket_take_profit_price")
            ),
            "TP Limit": show_price(
                order.get("bracket_take_profit_limit_price")
            ),
            "Status": order.get("state", "-")
        })

    st.dataframe(
        pd.DataFrame(pending_rows),
        use_container_width=True,
        hide_index=True
    )

else:
    st.info(
        "No pending LIMIT basket order."
    )


# ============================================================
# PENDING BASKET PLAN
# ============================================================

st.subheader("🧺 PENDING ENTRY + ATTACHED TP PLAN")

if target_baskets and signal_direction in ["BUY", "SELL"]:

    basket_rows = []

    for basket_name, basket_qty, basket_tp in target_baskets:
        basket_rows.append({
            "Basket": basket_name,
            "Entry LIMIT": show_price(limit_entry_price),
            "Qty": f"{basket_qty} contracts / {basket_qty * CONTRACT_BTC:.3f} BTC",
            "Attached TP": show_price(basket_tp),
            "TP Status": "ATTACHED TO ENTRY"
        })

    st.dataframe(
        pd.DataFrame(basket_rows),
        use_container_width=True,
        hide_index=True
    )

else:
    st.info("No active target basket plan.")


# ============================================================
# PLACE NEW REAL LIMIT ORDER
# ============================================================

st.subheader(
    "🚀 REAL LIMIT ORDER"
)


if not remote_enabled:

    st.warning(
        "Remote Control OFF — "
        "real order place nahi hoga."
    )

else:

    if not API_KEY or not API_SECRET:

        st.error(
            "API Key / API Secret missing."
        )

    elif signal_direction not in [
        "BUY",
        "SELL"
    ]:

        st.info(
            "Naya confirmed BUY/SELL signal ka wait hai."
        )

    else:

        current_signal_time = (
            signal_time
        )


        # ----------------------------------------------------
        # DUPLICATE / RESTART / RECONNECT SAFETY GUARD
        # ----------------------------------------------------
        # IMPORTANT:
        # Streamlit session_state is NOT enough because a mobile refresh,
        # app restart or reconnect can reset it.  The exchange is therefore
        # checked before EVERY new order.
        #
        # Rules:
        # 1) If Delta open-order check fails -> BLOCK new order.
        # 2) If Delta closed-order check fails -> BLOCK new order.
        # 3) If same-direction LIMIT order is already open -> BLOCK.
        # 4) If our latest completed order was already in the same direction
        #    -> BLOCK.  This protects even after that order was filled/cancelled.
        # 5) A new order is allowed only after BUY <-> SELL direction change.
        # 6) client_order_id is stable for the signal candle, so a rerun cannot
        #    create a different ID for the same signal.

        order_side = (
            "buy"
            if signal_direction == "BUY"
            else "sell"
        )

        signal_candle_epoch = int(float(current_entry["time"]))

        # Stable IDs: STB_BUY_<candle_epoch>_TP1
        # They do NOT use time.time(), so Streamlit reruns cannot generate
        # another ID for the same confirmed SuperTrend signal.
        stable_prefix = f"STB_{signal_direction}_{signal_candle_epoch}"

        same_direction_open = False
        opposite_direction_open = False

        for order in pending_orders:
            side = str(order.get("side", "")).lower()
            if side == order_side:
                same_direction_open = True
            elif side in ["buy", "sell"]:
                opposite_direction_open = True

        # Find the most recent order created by this dashboard.
        # Closed history catches orders that are already filled/cancelled.
        bot_history = []

        for order in closed_orders:
            try:
                product_id = int(
                    order.get("product_id", PRODUCT_ID)
                )
            except Exception:
                product_id = PRODUCT_ID

            if product_id != PRODUCT_ID:
                continue

            client_id = str(
                order.get("client_order_id", "")
            )

            if (
                client_id.startswith("STB_")
                or client_id.startswith("ST_BUY_")
                or client_id.startswith("ST_SELL_")
            ):
                bot_history.append(order)

        def _order_sort_key(order):
            for key in ("created_at_ts", "created_at", "id"):
                value = order.get(key)
                if value is None:
                    continue
                try:
                    return float(value)
                except Exception:
                    continue
            return 0

        # Newest bot order first.
        bot_history.sort(
            key=_order_sort_key,
            reverse=True
        )

        last_bot_direction = ""

        if bot_history:
            latest_bot = bot_history[0]
            latest_client_id = str(
                latest_bot.get("client_order_id", "")
            )

            if latest_client_id.startswith("STB_BUY_"):
                last_bot_direction = "BUY"
            elif latest_client_id.startswith("STB_SELL_"):
                last_bot_direction = "SELL"

        # Exact signal ID check as an extra layer.
        same_signal_already_seen = any(
            str(order.get("client_order_id", "")).startswith(
                stable_prefix
            )
            for order in pending_orders + closed_orders
        )

        # If the last dashboard order is the same direction, there has been
        # NO BUY<->SELL direction change.  Never place another order.
        same_direction_already_acted = (
            last_bot_direction == signal_direction
        )

        # Optional live-position safety:
        # if an existing position already points in the same direction as
        # the SuperTrend signal, do not create another entry.
        position_guard_response = api.position()
        position_guard_ok = bool(
            isinstance(position_guard_response, dict)
            and position_guard_response.get("success") is True
        )

        position_guard_data = get_result(
            position_guard_response
        )

        if isinstance(position_guard_data, list):
            guard_position = (
                position_guard_data[0]
                if position_guard_data
                else {}
            )
        elif isinstance(position_guard_data, dict):
            guard_position = position_guard_data
        else:
            guard_position = {}

        guard_size = number(
            guard_position.get("size"),
            0
        )

        same_direction_position = (
            (signal_direction == "BUY" and guard_size > 0)
            or
            (signal_direction == "SELL" and guard_size < 0)
        )

        # ----------------------------------------------------
        # HARD SAFETY: API verification must be complete.
        # ----------------------------------------------------
        if cancel_failed:
            st.error(
                "🛑 NEW ORDER BLOCKED — previous opposite basket "
                "cancel/verification was not completed successfully."
            )

        elif not open_orders_check_ok:
            st.error(
                "🛑 ORDER BLOCKED FOR SAFETY — "
                "Delta Exchange open-order duplicate-check की "
                "पूरी पुष्टि नहीं हो सकी. API check ठीक होने तक "
                "कोई नया order नहीं भेजा जाएगा."
            )

        elif not closed_orders_check_ok:
            st.error(
                "🛑 ORDER BLOCKED FOR SAFETY — "
                "Delta Exchange order-history duplicate-check की "
                "पूरी पुष्टि नहीं हो सकी. API check ठीक होने तक "
                "कोई नया order नहीं भेजा जाएगा."
            )

        elif not position_guard_ok:
            st.error(
                "🛑 ORDER BLOCKED FOR SAFETY — "
                "Delta Exchange position-check की पुष्टि नहीं हो सकी. "
                "API check ठीक होने तक कोई नया order नहीं भेजा जाएगा."
            )

        elif same_direction_open:
            st.success(
                f"🛡️ DUPLICATE BLOCKED — "
                f"पहले से {signal_direction} direction का "
                f"LIMIT order exchange पर मौजूद है. नया order नहीं भेजा गया."
            )

        elif same_signal_already_seen:
            st.success(
                f"🛡️ DUPLICATE BLOCKED — "
                f"{signal_direction} का यही confirmed signal पहले process हो चुका है. "
                f"नया order नहीं भेजा गया."
            )

        elif same_direction_already_acted:
            st.success(
                f"🛡️ SAME-DIRECTION BLOCKED — "
                f"पिछला dashboard order भी {signal_direction} था. "
                f"BUY ↔ SELL direction change के बिना नया order नहीं भेजा जाएगा."
            )

        elif same_direction_position:
            st.success(
                f"🛡️ POSITION BLOCKED — "
                f"पहले से {signal_direction} direction की live position मौजूद है. "
                f"नया entry order नहीं भेजा गया."
            )

        else:

            st.write(
                f"Signal: **{signal_direction}**"
            )

            st.write(
                f"LIMIT PRICE: "
                f"**{show_price(limit_entry_price)}**"
            )

            st.write(
                f"SIZE: **{order_size}**"
            )

            # ====================================================
            # AUTOMATIC BASKET EXECUTION
            # Each basket is a separate LIMIT entry with its own
            # attached bracket TP, all at the same entry price.
            # ====================================================

            basket_results = []
            all_baskets_ok = True

            for basket_index, (
                basket_name,
                basket_qty,
                basket_tp
            ) in enumerate(target_baskets, start=1):

                # Stable idempotency key based on the CONFIRMED SIGNAL
                # candle, not the current clock time.
                client_id = (
                    f"{stable_prefix}_{basket_name}"
                )

                result = api.place_limit_order(
                    side=order_side,
                    size=int(basket_qty),
                    limit_price=limit_entry_price,
                    take_profit_price=basket_tp,
                    client_order_id=client_id
                )

                basket_results.append({
                    "basket": basket_name,
                    "qty": basket_qty,
                    "tp": basket_tp,
                    "result": result
                })

                if not result.get("success"):
                    all_baskets_ok = False
                    st.error(
                        f"❌ {basket_name} FAILED: "
                        + str(
                            result.get(
                                "error",
                                "Unknown error"
                            )
                        )
                    )
                    break

            # If one basket failed, cancel baskets that were already
            # accepted so the signal does not remain partially armed.
            if not all_baskets_ok:

                for item in basket_results:
                    accepted = item.get("result", {})
                    accepted_data = accepted.get(
                        "result",
                        {}
                    )

                    accepted_id = (
                        accepted_data.get("id")
                        if isinstance(
                            accepted_data,
                            dict
                        )
                        else None
                    )

                    if accepted_id is not None:
                        api.cancel_order(accepted_id)

                st.session_state[
                    "pending_order_id"
                ] = None

            else:

                first_order_data = basket_results[0][
                    "result"
                ].get("result", {})

                first_order_id = (
                    first_order_data.get("id")
                    if isinstance(
                        first_order_data,
                        dict
                    )
                    else None
                )

                st.session_state[
                    "pending_order_id"
                ] = first_order_id

                st.session_state[
                    "pending_order_side"
                ] = order_side

                st.session_state[
                    "pending_order_time"
                ] = time.time()

                st.session_state[
                    "pending_basket_order_ids"
                ] = [
                    item["result"].get("result", {}).get("id")
                    for item in basket_results
                    if isinstance(
                        item["result"].get("result", {}),
                        dict
                    )
                ]

                # Keep the existing session protection as an additional
                # fast-path, but do NOT rely on it for safety.
                st.session_state[
                    "last_order_signal"
                ] = current_signal_time

                st.success(
                    f"✅ {len(basket_results)} REAL {signal_direction} "
                    f"LIMIT BASKET(S) SENT — TP ATTACHED TO EACH ENTRY"
                )

                for item in basket_results:
                    item_data = item["result"].get(
                        "result",
                        {}
                    )

                    item_id = (
                        item_data.get("id")
                        if isinstance(item_data, dict)
                        else None
                    )

                    st.write(
                        f"**{item['basket']}** — "
                        f"Entry {show_price(limit_entry_price)} | "
                        f"Qty {item['qty']} contracts "
                        f"({item['qty'] * CONTRACT_BTC:.3f} BTC) | "
                        f"TP {show_price(item['tp'])} | "
                        f"Order ID **{item_id}**"
                    )


# ============================================================
# CURRENT SIGNAL INFORMATION
# ============================================================

st.divider()

st.subheader(
    "📡 SIGNAL INFORMATION"
)

s1, s2, s3 = st.columns(3)


with s1:

    st.write(
        f"Direction: **{current_direction}**"
    )


with s2:

    st.write(
        f"Signal Entry: "
        f"**{show_price(signal_entry_price)}**"
    )


with s3:

    st.write(
        f"Signal Time: **{signal_time}**"
)
    # ============================================================
# PART 4/4
# REAL POSITION + ORDER STATUS + TARGET STATUS + REFRESH
# ============================================================

st.divider()

st.header("📍 REAL POSITION")


# ============================================================
# GET REAL POSITION
# ============================================================

position_response = api.position()

position_data = get_result(position_response)

if isinstance(position_data, list):

    if position_data:
        position = position_data[0]
    else:
        position = {}

elif isinstance(position_data, dict):

    position = position_data

else:

    position = {}


position_size = number(
    position.get("size"),
    0
)

position_entry = number(
    position.get("entry_price")
)

position_pnl = number(
    position.get("unrealized_pnl"),
    0
)


# ============================================================
# POSITION SIDE
# ============================================================

if position_size > 0:

    position_side = "LONG 🟢"

elif position_size < 0:

    position_side = "SHORT 🔴"

else:

    position_side = "FLAT ⚪"


p1, p2, p3, p4 = st.columns(4)


with p1:

    st.metric(
        "POSITION",
        position_side
    )


with p2:

    st.metric(
        "SIZE",
        str(abs(position_size))
    )


with p3:

    st.metric(
        "ENTRY PRICE",
        show_price(position_entry)
    )


with p4:

    st.metric(
        "UNREALIZED P&L",
        f"₹{position_pnl:,.2f}"
    )


# ============================================================
# ORDER STATUS
# ============================================================

st.header("📋 REAL ORDER STATUS")


orders_response = api.open_orders()

orders_result = get_result(
    orders_response
)


if isinstance(orders_result, list):

    open_orders = orders_result

else:

    open_orders = []


if open_orders:

    order_rows = []


    for order in open_orders:

        order_rows.append({

            "Order ID":
                order.get(
                    "id",
                    "-"
                ),

            "Side":
                str(
                    order.get(
                        "side",
                        ""
                    )
                ).upper(),

            "Type":
                order.get(
                    "order_type",
                    order.get(
                        "type",
                        "-"
                    )
                ),

            "Price":
                show_price(
                    order.get(
                        "limit_price"
                    )
                ),

            "Size":
                order.get(
                    "size",
                    "-"
                ),

            "Attached TP":
                show_price(
                    order.get(
                        "bracket_take_profit_price"
                    )
                ),

            "Client/Basket":
                order.get(
                    "client_order_id",
                    "-"
                ),

            "State":
                order.get(
                    "state",
                    "-"
                )
        })


    st.dataframe(
        pd.DataFrame(
            order_rows
        ),
        use_container_width=True,
        hide_index=True
    )

else:

    st.info(
        "No open orders."
    )


# ============================================================
# TARGET STATUS
# ============================================================

st.header("🎯 TARGET STATUS")


if signal_direction == "BUY":

    target_direction = "LONG"

elif signal_direction == "SELL":

    target_direction = "SHORT"

else:

    target_direction = "NONE"


tc1, tc2, tc3, tc4 = st.columns(4)


with tc1:

    st.metric(
        "DIRECTION",
        target_direction
    )


with tc2:

    st.metric(
        "TARGET 1",
        show_price(target1)
    )


with tc3:

    st.metric(
        "TARGET 2",
        show_price(target2)
    )


with tc4:

    st.metric(
        "TARGET 3",
        show_price(target3)
    )


# ============================================================
# TARGET DISTANCE
# ============================================================

if signal_direction in ["BUY", "SELL"]:

    st.write(
        f"Entry: **{show_price(limit_entry_price)}**"
    )

    st.write(
        f"T1: **{show_price(target1)}**"
    )

    st.write(
        f"T2: **{show_price(target2)}**"
    )

    st.write(
        f"T3: **{show_price(target3)}**"
    )


# ============================================================
# LIVE MARKET PRICE
# ============================================================

st.header("💰 LIVE MARKET PRICE")


ticker_response = api.ticker()

ticker_result = get_result(
    ticker_response
)


if isinstance(ticker_result, dict):

    live_price = None


    for key in [
        "close",
        "last_price",
        "mark_price",
        "spot_price"
    ]:

        value = number(
            ticker_result.get(key)
        )


        if value is not None:

            live_price = value

            break


else:

    live_price = None


st.metric(
    "BTCUSD",
    show_price(live_price)
)


# ============================================================
# SIGNAL / ORDER SUMMARY
# ============================================================

st.header("📊 TRADING SUMMARY")


summary_rows = [

    {
        "Item": "SuperTrend Direction",
        "Value": current_direction
    },

    {
        "Item": "Signal Entry",
        "Value": show_price(
            signal_entry_price
        )
    },

    {
        "Item": "Limit Entry",
        "Value": show_price(
            limit_entry_price
        )
    },

    {
        "Item": "Target 1",
        "Value": show_price(
            target1
        )
    },

    {
        "Item": "Target 2",
        "Value": show_price(
            target2
        )
    },

    {
        "Item": "Target 3",
        "Value": show_price(
            target3
        )
    },

    {
        "Item": "Basket Plan",
        "Value": " | ".join(
            f"{name}: {qty * CONTRACT_BTC:.3f} BTC → {show_price(tp)}"
            for name, qty, tp in target_baskets
        ) if target_baskets else "-"
    },

    {
        "Item": "Signal Time",
        "Value": signal_time
    },

    {
        "Item": "Remote Trading",
        "Value": (
            "ON 🔴"
            if remote_enabled
            else "OFF 🟢"
        )
    }
]


st.dataframe(
    pd.DataFrame(
        summary_rows
    ),
    use_container_width=True,
    hide_index=True
)


# ============================================================
# SAFETY INFORMATION
# ============================================================

st.divider()

st.subheader(
    "⚠️ REAL TRADING SAFETY"
)

if remote_enabled:

    st.error(
        "REAL TRADING ACTIVE — "
        "Dashboard se exchange orders bheje ja sakte hain."
    )

else:

    st.success(
        "REAL TRADING OFF — "
        "Dashboard order place nahi karega."
    )


st.write(
    "Pending LIMIT order ka direction "
    "SuperTrend se opposite hone par "
    "automatic cancellation Part 3 mein enabled hai."
)


# ============================================================
# INDIAN TIME
# ============================================================

now_ist = datetime.now(
    timezone.utc
).astimezone(IST)


st.write(
    "Dashboard Time: "
    f"**{now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}**"
)


# ============================================================
# AUTO REFRESH
# ============================================================

# ============================================================
# ORIGINAL TRADINGVIEW CHART — VIEW ONLY
# ============================================================

components.html(
    """
    <div
        class="tradingview-widget-container"
        style="height:700vh;width:100%;">

        <div
            class="tradingview-widget-container__widget"
            style="height:700%;width:100%;">
        </div>

        <script
            type="text/javascript"
            src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
            async>

        {
            
            "autosize": false,
            "height": 700,
            "symbol": "BINANCE:BTCUSDT",
            "interval": "5",
            "timezone": "Asia/Kolkata",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "enable_publishing": false,
            "allow_symbol_change": true,
            "hide_top_toolbar": false,
            "hide_legend": false,
            "save_image": false,
            "hide_volume": false,
            "support_host": "https://www.tradingview.com"
        }

        </script>
    </div>
    """,
    height=1200,
    scrolling=False
)

# ============================================================
# END OF PART 1
# PART 2 = CANDLE + SUPERTREND ENGINE
# ============================================================
time.sleep(REFRESH_SECONDS)
st.rerun()

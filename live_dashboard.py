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

TIMEFRAME = "1m"
CANDLE_SECONDS = 60

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
    os.getenv("BUY_OFFSET", "-10")
)

DEFAULT_SELL_OFFSET = int(
    os.getenv("SELL_OFFSET", "10")
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
    os.getenv("LIMIT_TIMEOUT", "6000000")
)

TARGET_1 = int(os.getenv("TARGET_1", "500"))
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

st.title("📈 SANJAY RANA — REAL TRADING DASHBOARD 8930814389")

st.caption(
    "1 Minute | ATR 10 | Multiplier 3.0 | HL2 | "
    "Confirmed Candle Close"
)


# ============================================================
# INDIAN TIME
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))

# ============================================================
# LIVE EVENT NOTIFICATION STORE
# Dashboard + background worker share this small local event log.
# It is monitoring-only and does not change trading logic.
# ============================================================
EVENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_events.json")
_EVENT_LOCK = __import__("threading").Lock()

def record_event(event_type, message, details=None):
    event = {
        "time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "type": str(event_type),
        "message": str(message),
        "details": details or {},
    }
    try:
        with _EVENT_LOCK:
            events = []
            if os.path.exists(EVENT_FILE):
                try:
                    with open(EVENT_FILE, "r", encoding="utf-8") as f:
                        events = json.load(f)
                except Exception:
                    events = []
            if not isinstance(events, list):
                events = []
            events.append(event)
            events = events[-100:]
            tmp = EVENT_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(events, f, ensure_ascii=False)
            os.replace(tmp, EVENT_FILE)
    except Exception:
        pass

def read_events(limit=20):
    try:
        with open(EVENT_FILE, "r", encoding="utf-8") as f:
            events = json.load(f)
        return events[-limit:] if isinstance(events, list) else []
    except Exception:
        return []


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
# ADDITIVE ORDER LIFECYCLE TRACKING
# Existing trading logic is intentionally left unchanged.
# ============================================================

def _order_epoch(value):
    if value is None:
        return None
    try:
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        return ts
    except Exception:
        return None


def _order_event_epoch(order, keys):
    for key in keys:
        if key in order and order.get(key) not in [None, ""]:
            ts = _order_epoch(order.get(key))
            if ts is not None:
                return ts
    return None


def _format_epoch(ts):
    if ts is None:
        return "-"
    return indian_time(ts)


def _duration_text(seconds):
    if seconds is None:
        return "-"
    try:
        seconds = max(0, int(seconds))
    except Exception:
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m {secs}s"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _ensure_order_tracking():
    if "order_tracking" not in st.session_state:
        st.session_state["order_tracking"] = {}
    return st.session_state["order_tracking"]


def _remember_sent_order(order_id, data):
    if order_id is None:
        return
    tracking = _ensure_order_tracking()
    tracking[str(order_id)] = dict(data)


def _order_status_label(order):
    state = str(order.get("state", "")).lower()
    if state in {"filled", "closed"}:
        return "EXECUTED / CLOSED"
    if state in {"cancelled", "canceled"}:
        return "CANCELLED"
    if state in {"rejected", "failed"}:
        return "REJECTED"
    if state in {"open", "pending", "active", "partially_filled"}:
        return "PENDING"
    return str(order.get("state", "-")).upper()


def _order_sent_epoch(order):
    return _order_event_epoch(
        order,
        (
            "created_at_ts",
            "created_at",
            "created_time",
            "timestamp"
        )
    )


def _order_final_epoch(order):
    return _order_event_epoch(
        order,
        (
            "filled_at",
            "executed_at",
            "closed_at",
            "cancelled_at",
            "canceled_at",
            "updated_at"
        )
    )


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

    def wallet_balances(self):
        return self.request(
            "GET",
            "/v2/wallet/balances",
            private=True
        )

    def order_leverage(self):
        return self.request(
            "GET",
            f"/v2/products/{PRODUCT_ID}/orders/leverage",
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
    # MARKET REDUCE-ONLY ORDER — CLOSE OPPOSITE POSITION
    # --------------------------------------------------------

    def place_market_reduce_only(self, side, size, client_order_id=None):

        body = {
            "product_id": PRODUCT_ID,
            "product_symbol": SYMBOL,
            "size": int(abs(size)),
            "side": side,
            "order_type": "market_order",
            "reduce_only": True,
        }

        if client_order_id:
            body["client_order_id"] = str(client_order_id)[:32]

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

        try:
            order_id_value = int(order_id)
        except Exception:
            order_id_value = order_id

        return self.request(
            "DELETE",
            "/v2/orders",
            body={
                "id": order_id_value,
                "product_id": PRODUCT_ID
            },
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
# CONNECTION DISCONNECT / RECONNECT TIME TRACKER
# ============================================================
# यह केवल connection status का monitoring block है।
# Existing trading/order logic को नहीं बदलता।

_now_connection_ist = datetime.now(timezone.utc).astimezone(IST)
_now_connection_text = _now_connection_ist.strftime("%Y-%m-%d %H:%M:%S IST")

if "connection_was_connected" not in st.session_state:
    st.session_state["connection_was_connected"] = None

if "disconnect_started_at" not in st.session_state:
    st.session_state["disconnect_started_at"] = ""

if "last_reconnected_at" not in st.session_state:
    st.session_state["last_reconnected_at"] = ""

if "last_connection_check_at" not in st.session_state:
    st.session_state["last_connection_check_at"] = ""

_current_connection_ok = bool(
    st.session_state.get("owner_api_connected", False)
)

if _current_connection_ok:
    # अगर पहले disconnect था और अब connection वापस आया है
    if (
        st.session_state["connection_was_connected"] is False
        and st.session_state["disconnect_started_at"]
    ):
        st.session_state["last_reconnected_at"] = _now_connection_text
        record_event("RECONNECTED", "Delta API reconnected successfully.")
    elif st.session_state["connection_was_connected"] is None:
        record_event("CONNECTED", "Delta API connected successfully.")

    st.session_state["connection_was_connected"] = True
    st.session_state["last_connection_check_at"] = _now_connection_text

else:
    # पहली बार disconnect detect होने का exact समय
    if st.session_state["connection_was_connected"] is not False:
        st.session_state["disconnect_started_at"] = _now_connection_text
        record_event("DISCONNECTED", "Delta API disconnected or health check failed.")

    st.session_state["connection_was_connected"] = False
    st.session_state["last_connection_check_at"] = _now_connection_text

st.divider()
st.subheader("📡 CONNECTION DISCONNECT MONITOR")

if _current_connection_ok:
    st.success("🟢 CONNECTION: CONNECTED")

    st.write(
        "Last Successful Connection: "
        f"**{st.session_state['last_connection_check_at']}**"
    )

    if st.session_state["last_reconnected_at"]:
        st.info(
            "🟢 RECONNECTED AT: "
            f"**{st.session_state['last_reconnected_at']}**"
        )

        if st.session_state["disconnect_started_at"]:
            st.write(
                "Previous Disconnect Started At: "
                f"**{st.session_state['disconnect_started_at']}**"
            )
    else:
        st.write(
            "Disconnect History: **No disconnect detected in this session**"
        )

else:
    st.error("🔴 CONNECTION: DISCONNECTED")

    st.write(
        "Disconnected At: "
        f"**{st.session_state['disconnect_started_at']}**"
    )

    st.write(
        "Last Connection Check: "
        f"**{st.session_state['last_connection_check_at']}**"
    )


# ============================================================
# ACCOUNT BALANCE + LEVERAGE + LIVE NOTIFICATIONS
# Monitoring only — does not change order/trading rules.
# ============================================================
st.divider()
st.subheader("💰 ACCOUNT BALANCE & LEVERAGE")

if st.session_state.get("owner_api_connected", False) and OWNER_API_KEY and OWNER_API_SECRET:
    try:
        account_client = DeltaAPI(OWNER_API_KEY, OWNER_API_SECRET)
        wallet_result = account_client.wallet_balances()
        leverage_result = account_client.order_leverage()

        wallet_rows = wallet_result.get("result", []) if isinstance(wallet_result, dict) else []
        if not isinstance(wallet_rows, list):
            wallet_rows = []

        # Prefer the USD-settled wallet when present; otherwise show the first wallet.
        wallet = next((w for w in wallet_rows if str(w.get("asset_symbol", "")).upper() == "USD"), None)
        if wallet is None and wallet_rows:
            wallet = wallet_rows[0]

        total_balance = wallet.get("balance", "-") if wallet else "-"
        available_balance = wallet.get("available_balance", "-") if wallet else "-"
        asset_symbol = wallet.get("asset_symbol", "-") if wallet else "-"

        lev_data = leverage_result.get("result", {}) if isinstance(leverage_result, dict) else {}
        leverage_value = lev_data.get("leverage", "-") if isinstance(lev_data, dict) else "-"
        order_margin = lev_data.get("order_margin", "-") if isinstance(lev_data, dict) else "-"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Balance", f"{total_balance} {asset_symbol}" if asset_symbol != "-" else str(total_balance))
        c2.metric("Available Balance", f"{available_balance} {asset_symbol}" if asset_symbol != "-" else str(available_balance))
        c3.metric("Leverage", f"{leverage_value}x" if leverage_value != "-" else "-")
        c4.metric("Open Order Margin", str(order_margin))
    except Exception as e:
        st.warning(f"Account balance/leverage read failed: {e}")
else:
    st.info("Account balance/leverage will appear after API connection is established.")


st.subheader("🔔 LIVE TRADING NOTIFICATIONS")
_events = list(reversed(read_events(20)))
if _events:
    for _ev in _events:
        _etype = str(_ev.get("type", "INFO")).upper()
        _msg = str(_ev.get("message", ""))
        _time = str(_ev.get("time", ""))
        if _etype in ("BUY", "SELL", "TRADE"):
            st.success(f"🟢 {_time} — {_msg}") if _etype == "BUY" else st.error(f"🔴 {_time} — {_msg}")
        elif _etype == "CONNECTED" or _etype == "RECONNECTED":
            st.success(f"🟢 {_time} — {_msg}")
        elif _etype == "DISCONNECTED" or _etype == "ERROR":
            st.error(f"🔴 {_time} — {_msg}")
        else:
            st.info(f"🔵 {_time} — {_msg}")
else:
    st.caption("No trading/connection notifications yet.")


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
# ONLY COMPLETED 1-MINUTE CANDLES
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
# Reference chart: regular Delta BTCUSD 1-minute candles,
# SuperTrend 10 3, Source = HL2.
#
# This is NOT Heikin-Ashi.
# ATR = TradingView-style Wilder/RMA.
# Only completed 1-minute Delta candles reach this engine.
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


BACKGROUND_WORKER_ACTIVE = True

if not BACKGROUND_WORKER_ACTIVE:
    # ============================================================
    # CANCEL OLD OPPOSITE BASKETS ON SUPERTREND DIRECTION CHANGE
    # ============================================================
    # BUY signal  -> cancel old SELL entry + attached TP orders
    # SELL signal -> cancel old BUY entry + attached TP orders
    # After cancellation, refresh open orders before allowing a new entry.

    cancel_failed = False
    position_close_failed = False
    cancelled_order_ids = set()

    if remote_enabled and signal_direction in ["BUY", "SELL"]:

        expected_new_side = (
            "buy" if signal_direction == "BUY" else "sell"
        )

        opposite_side = (
            "sell" if expected_new_side == "buy" else "buy"
        )

        # --------------------------------------------------------
        # 1) CANCEL EVERY OLD OPPOSITE-SIDE OPEN ORDER
        #    This includes Entry LIMIT and any separate TP/SL order
        #    that Delta reports as an open order.
        # --------------------------------------------------------
        for order in list(open_orders):

            order_id = order.get("id")
            order_side = str(order.get("side", "")).lower()

            if order_side != opposite_side or order_id is None:
                continue

            cancel_result = api.cancel_order(order_id)

            if (
                isinstance(cancel_result, dict)
                and cancel_result.get("success")
            ):
                cancelled_order_ids.add(str(order_id))

                st.warning(
                    f"🔄 OLD {order_side.upper()} ORDER CANCELLED — "
                    f"SuperTrend changed to {signal_direction}."
                )

                if order_id == st.session_state.get("pending_order_id"):
                    st.session_state["pending_order_id"] = None

            else:
                cancel_failed = True
                st.error(
                    "🛑 OLD OPPOSITE ORDER CANCEL FAILED — "
                    "NEW ORDER BLOCKED."
                )

        # --------------------------------------------------------
        # 2) CHECK LIVE POSITION
        #    If position is opposite to the new SuperTrend direction,
        #    close/reduce it completely before placing the new entry.
        # --------------------------------------------------------
        if not cancel_failed:

            cleanup_position_response = api.position()
            cleanup_position_ok = bool(
                isinstance(cleanup_position_response, dict)
                and cleanup_position_response.get("success") is True
            )

            if not cleanup_position_ok:
                position_close_failed = True
                st.error(
                    "🛑 POSITION CHECK FAILED — NEW ORDER BLOCKED. "
                    "Delta position could not be verified."
                )
            else:
                cleanup_position_data = get_result(
                    cleanup_position_response
                )

                if isinstance(cleanup_position_data, list):
                    cleanup_position = (
                        cleanup_position_data[0]
                        if cleanup_position_data
                        else {}
                    )
                elif isinstance(cleanup_position_data, dict):
                    cleanup_position = cleanup_position_data
                else:
                    cleanup_position = {}

                cleanup_position_size = number(
                    cleanup_position.get("size"),
                    0
                )

                opposite_position_exists = (
                    (signal_direction == "BUY" and cleanup_position_size < 0)
                    or
                    (signal_direction == "SELL" and cleanup_position_size > 0)
                )

                if opposite_position_exists:

                    close_side = "buy" if cleanup_position_size < 0 else "sell"
                    close_size = abs(int(cleanup_position_size))

                    if close_size <= 0:
                        position_close_failed = True
                        st.error(
                            "🛑 OPPOSITE POSITION SIZE INVALID — "
                            "NEW ORDER BLOCKED."
                        )
                    else:
                        close_result = api.place_market_reduce_only(
                            side=close_side,
                            size=close_size,
                            client_order_id=(
                                f"STB_CLOSE_{signal_direction}_{int(time.time())}"
                            )
                        )

                        if (
                            isinstance(close_result, dict)
                            and close_result.get("success")
                        ):
                            # ADDITIVE: remember this reduce-only EXIT order.
                            _close_data = close_result.get("result", {})
                            if isinstance(_close_data, dict):
                                _close_id = _close_data.get("id")
                                if _close_id is not None:
                                    _remember_sent_order(
                                        _close_id,
                                        {
                                            "sent_epoch": time.time(),
                                            "sent_text": _format_epoch(time.time()),
                                            "signal": signal_direction,
                                            "basket": "POSITION EXIT",
                                            "qty": close_size,
                                            "tp": None,
                                            "limit_price": None,
                                            "kind": "EXIT"
                                        }
                                    )

                            st.warning(
                                f"🔄 OLD OPPOSITE POSITION CLOSED/REDUCED — "
                                f"{abs(cleanup_position_size)} contracts."
                            )
                        else:
                            position_close_failed = True
                            st.error(
                                "🛑 OPPOSITE POSITION CLOSE/REDUCE FAILED — "
                                "NEW ORDER BLOCKED."
                            )

        # --------------------------------------------------------
        # 3) FINAL EXCHANGE VERIFICATION
        #    Do not trust the old Streamlit snapshot.
        # --------------------------------------------------------
        if not cancel_failed and not position_close_failed:

            refreshed_open_response = api.open_orders()
            refreshed_open_ok = bool(
                isinstance(refreshed_open_response, dict)
                and refreshed_open_response.get("success") is True
            )

            if not refreshed_open_ok:
                cancel_failed = True
                st.error(
                    "🛑 OPEN-ORDER VERIFICATION FAILED — "
                    "NEW ORDER BLOCKED."
                )
            else:
                refreshed_open_orders = get_result(
                    refreshed_open_response
                )

                if not isinstance(refreshed_open_orders, list):
                    refreshed_open_orders = []

                # Any opposite-side open order means the old direction
                # is not fully cleared. Never place the new basket.
                for order in refreshed_open_orders:
                    side = str(order.get("side", "")).lower()

                    if side == opposite_side:
                        cancel_failed = True
                        st.error(
                            "🛑 OLD OPPOSITE ENTRY/TP ORDER IS STILL OPEN — "
                            "NEW ORDER BLOCKED FOR SAFETY."
                        )
                        break

                # Verify the position again after the reduce-only close.
                if not cancel_failed:
                    final_position_response = api.position()
                    final_position_ok = bool(
                        isinstance(final_position_response, dict)
                        and final_position_response.get("success") is True
                    )

                    if not final_position_ok:
                        position_close_failed = True
                        st.error(
                            "🛑 FINAL POSITION VERIFICATION FAILED — "
                            "NEW ORDER BLOCKED."
                        )
                    else:
                        final_position_data = get_result(
                            final_position_response
                        )

                        if isinstance(final_position_data, list):
                            final_position = (
                                final_position_data[0]
                                if final_position_data
                                else {}
                            )
                        elif isinstance(final_position_data, dict):
                            final_position = final_position_data
                        else:
                            final_position = {}

                        final_position_size = number(
                            final_position.get("size"),
                            0
                        )

                        opposite_position_remaining = (
                            (signal_direction == "BUY" and final_position_size < 0)
                            or
                            (signal_direction == "SELL" and final_position_size > 0)
                        )

                        if opposite_position_remaining:
                            position_close_failed = True
                            st.error(
                                "🛑 OLD OPPOSITE POSITION IS STILL OPEN — "
                                "NEW ORDER BLOCKED FOR SAFETY."
                            )

                if not cancel_failed and not position_close_failed:
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

    # If any old opposite order/position could not be cleared and verified,
    # no new entry is allowed.

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
            if cancel_failed or position_close_failed:
                st.error(
                    "🛑 NEW ORDER BLOCKED — previous opposite orders/position "
                    "were not fully cleared and verified."
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

                    # ADDITIVE: remember the exact local time when Delta accepted
                    # this order. This is only tracking; it does not alter order flow.
                    if result.get("success"):
                        _accepted_data = result.get("result", {})
                        if isinstance(_accepted_data, dict):
                            _accepted_id = _accepted_data.get("id")
                            if _accepted_id is not None:
                                _remember_sent_order(
                                    _accepted_id,
                                    {
                                        "sent_epoch": time.time(),
                                        "sent_text": _format_epoch(time.time()),
                                        "signal": signal_direction,
                                        "basket": basket_name,
                                        "qty": basket_qty,
                                        "tp": basket_tp,
                                        "limit_price": limit_entry_price,
                                        "kind": "ENTRY"
                                    }
                                )

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
# COMPLETE ORDER LIFECYCLE / HISTORY
# ADDITIVE DISPLAY ONLY — EXISTING ORDER LOGIC IS UNCHANGED.
# ============================================================

st.divider()
st.header("🧾 COMPLETE ORDER LIFECYCLE / HISTORY")

_lifecycle_open_response = api.open_orders()
_lifecycle_closed_response = api.closed_orders()

_lifecycle_open = get_result(_lifecycle_open_response)
_lifecycle_closed = get_result(_lifecycle_closed_response)

if not isinstance(_lifecycle_open, list):
    _lifecycle_open = []

if not isinstance(_lifecycle_closed, list):
    _lifecycle_closed = []

_lifecycle_tracking = _ensure_order_tracking()

# Build one combined list. Open orders represent current PENDING status;
# closed orders provide EXECUTED / CANCELLED / REJECTED history.
_lifecycle_orders = []

for _source_name, _source_orders in (
    ("OPEN", _lifecycle_open),
    ("CLOSED", _lifecycle_closed),
):
    for _order in _source_orders:
        try:
            _pid = int(_order.get("product_id", PRODUCT_ID))
        except Exception:
            _pid = PRODUCT_ID

        if _pid != PRODUCT_ID:
            continue

        _client_id = str(_order.get("client_order_id", ""))
        _oid = _order.get("id")

        # Only dashboard-created orders plus orders remembered by this
        # dashboard session are shown in this new lifecycle panel.
        _is_dashboard_order = (
            _client_id.startswith("STB_")
            or _client_id.startswith("ST_BUY_")
            or _client_id.startswith("ST_SELL_")
            or str(_oid) in _lifecycle_tracking
        )

        if _is_dashboard_order:
            _lifecycle_orders.append(_order)

# De-duplicate by exchange order ID.
_lifecycle_unique = {}
for _order in _lifecycle_orders:
    _oid = _order.get("id")
    if _oid is not None:
        _lifecycle_unique[str(_oid)] = _order

_lifecycle_rows = []

for _oid, _order in _lifecycle_unique.items():
    _tracking = _lifecycle_tracking.get(str(_oid), {})

    _state = str(_order.get("state", "")).lower()
    _status = _order_status_label(_order)

    _sent_ts = _order_sent_epoch(_order)
    if _sent_ts is None:
        _sent_ts = _order_epoch(_tracking.get("sent_epoch"))

    _final_ts = _order_final_epoch(_order)

    # For a still-open order, duration runs until the current refresh.
    if _status == "PENDING":
        _duration = (
            time.time() - _sent_ts
            if _sent_ts is not None
            else None
        )
    else:
        _duration = (
            _final_ts - _sent_ts
            if _sent_ts is not None and _final_ts is not None
            else None
        )

    _reduce_only = bool(_order.get("reduce_only", False))
    _order_type = str(
        _order.get(
            "order_type",
            _order.get("type", "-")
        )
    )

    if (
        _tracking.get("kind") == "EXIT"
        or _reduce_only
        or "close" in str(_order.get("client_order_id", "")).lower()
    ):
        _kind = "EXIT"
    else:
        _kind = _tracking.get("kind", "ENTRY")

    _executed_price = (
        _order.get("average_fill_price")
        or _order.get("avg_fill_price")
        or _order.get("fill_price")
        or _order.get("average_price")
    )

    _lifecycle_rows.append({
        "Order ID": _oid,
        "Kind": _kind,
        "Basket": _tracking.get(
            "basket",
            _order.get("client_order_id", "-")
        ),
        "Side": str(_order.get("side", "")).upper(),
        "Qty": _order.get("size", _tracking.get("qty", "-")),
        "Order Price": show_price(
            _order.get(
                "limit_price",
                _tracking.get("limit_price")
            )
        ),
        "Executed Price": show_price(_executed_price),
        "Sent At": _format_epoch(_sent_ts),
        "Executed/Cancelled At": _format_epoch(_final_ts),
        "Pending/Active For": _duration_text(_duration),
        "Status": _status,
        "Exchange State": _state.upper() or "-",
        "Client/Basket ID": _order.get(
            "client_order_id",
            "-"
        ),
        "Order Type": _order_type,
    })

# Also keep locally remembered orders visible if the exchange has not yet
# returned them in the current open/closed response.
_seen_ids = {str(x.get("Order ID")) for x in _lifecycle_rows}
for _oid, _tracking in _lifecycle_tracking.items():
    if str(_oid) in _seen_ids:
        continue
    _lifecycle_rows.append({
        "Order ID": _oid,
        "Kind": _tracking.get("kind", "ENTRY"),
        "Basket": _tracking.get("basket", "-"),
        "Side": str(_tracking.get("signal", "")).upper(),
        "Qty": _tracking.get("qty", "-"),
        "Order Price": show_price(_tracking.get("limit_price")),
        "Executed Price": "-",
        "Sent At": _tracking.get("sent_text", "-"),
        "Executed/Cancelled At": "-",
        "Pending/Active For": _duration_text(
            time.time() - _tracking.get("sent_epoch", time.time())
        ),
        "Status": "PENDING — EXCHANGE STATUS NOT YET RETURNED",
        "Exchange State": "-",
        "Client/Basket ID": "-",
        "Order Type": "-",
    })

if _lifecycle_rows:
    _lifecycle_rows.sort(
        key=lambda row: str(row.get("Order ID", "")),
        reverse=True
    )
    st.dataframe(
        pd.DataFrame(_lifecycle_rows),
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("अभी इस Dashboard के लिए कोई order lifecycle history उपलब्ध नहीं है।")

st.caption(
    "🟡 PENDING = exchange पर order खड़ा है और अभी execute नहीं हुआ। "
    "🟢 EXECUTED/CLOSED = exchange ने order पूरा/close किया। "
    "🔴 CANCELLED = order execute हुए बिना cancel हुआ। "
    "EXIT = reduce-only/position-close order."
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
            "studies": [
    {
        "id": "SuperTrend@tv-basicstudies",
        "inputs": {
            "length": 10,
            "factor": 3
        }
    }
],
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
    height=700,
    scrolling=False
)

# ============================================================
# END OF PART 1
# PART 2 = CANDLE + SUPERTREND ENGINE
# ============================================================
# Background worker is started once per Streamlit Python process below.

# ============================================================
# SANJAY RANA — BACKGROUND TRADING WORKER
# Same Streamlit/Delta environment + same outbound IP as dashboard.
# ============================================================

import os
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd

BASE_URL = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange").rstrip("/")
SYMBOL = os.getenv("DELTA_SYMBOL", "BTCUSD")
PRODUCT_ID = int(os.getenv("DELTA_PRODUCT_ID", "27"))

TIMEFRAME = "1m"
CANDLE_SECONDS = 60
ATR_PERIOD = 10
MULTIPLIER = 3.0

ORDER_QTY = float(os.getenv("ORDER_QTY", "0.001"))
CONTRACT_BTC = 0.001
DEFAULT_BUY_OFFSET = int(os.getenv("BUY_OFFSET", "-150"))
DEFAULT_SELL_OFFSET = int(os.getenv("SELL_OFFSET", "150"))
TARGET_1 = int(os.getenv("TARGET_1", "200"))
TARGET_2 = int(os.getenv("TARGET_2", "600"))
TARGET_3 = int(os.getenv("TARGET_3", "900"))

if ORDER_QTY <= 0:
    raise ValueError("ORDER_QTY must be greater than 0")

_total_contracts = ORDER_QTY / CONTRACT_BTC
if abs(_total_contracts - round(_total_contracts)) > 1e-9:
    raise ValueError("ORDER_QTY must be a multiple of 0.001 BTC")

DEFAULT_ORDER_SIZE = int(round(_total_contracts))

API_KEY = ""
API_SECRET = ""

WORKER_DIR = Path(__file__).resolve().parent
PID_FILE = WORKER_DIR / "background_worker.pid"
LOG_FILE = WORKER_DIR / "background_worker.log"
LOCK_FILE = WORKER_DIR / "background_worker.lock"

IST = timezone(timedelta(hours=5, minutes=30))

def log(message):
    line = f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}] {message}"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)

def write_pid():
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

def remove_pid():
    try:
        if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except Exception:
        pass

try:
    import fcntl
except Exception:
    fcntl = None

_lock_handle = None

def acquire_worker_lock():
    global _lock_handle
    if fcntl is None:
        return True
    _lock_handle = LOCK_FILE.open("a+", encoding="utf-8")
    try:
        fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False

def number(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

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

    return (
        pd.DataFrame(rows)
        .drop_duplicates("time")
        .sort_values("time")
        .reset_index(drop=True)
    )

# ============================================================
# EXACT DELTA API CLASS FROM THE DASHBOARD
# ============================================================

class _EmbeddedWorkerDeltaAPI:

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
    # MARKET REDUCE-ONLY ORDER — CLOSE OPPOSITE POSITION
    # --------------------------------------------------------

    def place_market_reduce_only(self, side, size, client_order_id=None):

        body = {
            "product_id": PRODUCT_ID,
            "product_symbol": SYMBOL,
            "size": int(abs(size)),
            "side": side,
            "order_type": "market_order",
            "reduce_only": True,
        }

        if client_order_id:
            body["client_order_id"] = str(client_order_id)[:32]

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

        try:
            order_id_value = int(order_id)
        except Exception:
            order_id_value = order_id

        return self.request(
            "DELETE",
            "/v2/orders",
            body={
                "id": order_id_value,
                "product_id": PRODUCT_ID
            },
            private=True
        )

# ============================================================
# TARGET BASKETS — SAME DASHBOARD LOGIC
# ============================================================

def build_target_baskets(total_contracts, target1, target2, target3):
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

# ============================================================
# SUPERTREND — SAME 10,3 HL2 COMPLETED-CANDLE LOGIC
# ============================================================

def get_signal(api):
    candle_response = api.candles()
    df = make_dataframe(candle_response)

    if df.empty:
        return None

    current_candle_start = (int(time.time()) // CANDLE_SECONDS) * CANDLE_SECONDS

    df = df[df["time"] < current_candle_start].copy().reset_index(drop=True)

    if len(df) < ATR_PERIOD + 5:
        return None

    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    df["ATR"] = float("nan")

    if len(df) >= ATR_PERIOD:
        df.loc[ATR_PERIOD - 1, "ATR"] = df["TR"].iloc[:ATR_PERIOD].mean()

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

            if basic_upper < prev_final_upper or previous_close > prev_final_upper:
                final_upper = basic_upper
            else:
                final_upper = prev_final_upper

            if basic_lower > prev_final_lower or previous_close < prev_final_lower:
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

    signal_rows = df[df["SIGNAL"].isin(["BUY", "SELL"])].copy()

    if signal_rows.empty:
        return {
            "signal_direction": "",
            "signal_entry_price": float(df.iloc[-1]["close"]),
            "signal_time": int(df.iloc[-1]["time"]),
            "candle_time": int(df.iloc[-1]["time"])
        }

    current_entry = signal_rows.iloc[-1]

    return {
        "signal_direction": str(current_entry["SIGNAL"]),
        "signal_entry_price": float(current_entry["close"]),
        "signal_time": int(current_entry["time"]),
        "candle_time": int(current_entry["time"])
    }

# ============================================================
# ORDER EXECUTION — SAME SAFETY GUARDS
# ============================================================

def _embedded_worker_cycle(api, worker_key, worker_secret):
    global API_KEY, API_SECRET
    API_KEY = worker_key
    API_SECRET = worker_secret
    signal = get_signal(api)

    if not signal:
        log("Candle/API data unavailable — cycle skipped.")
        return

    signal_direction = signal["signal_direction"]

    if signal_direction not in ["BUY", "SELL"]:
        log("No confirmed BUY/SELL signal — no new order.")
        return

    signal_entry_price = signal["signal_entry_price"]
    signal_candle_epoch = int(float(signal["candle_time"]))

    if signal_direction == "BUY":
        limit_entry_price = signal_entry_price + float(DEFAULT_BUY_OFFSET)
        target1 = limit_entry_price + TARGET_1
        target2 = limit_entry_price + TARGET_2
        target3 = limit_entry_price + TARGET_3
        order_side = "buy"
        opposite_side = "sell"
    else:
        limit_entry_price = signal_entry_price + float(DEFAULT_SELL_OFFSET)
        target1 = limit_entry_price - TARGET_1
        target2 = limit_entry_price - TARGET_2
        target3 = limit_entry_price - TARGET_3
        order_side = "sell"
        opposite_side = "buy"

    target_baskets = build_target_baskets(
        DEFAULT_ORDER_SIZE, target1, target2, target3
    )

    open_orders_response = api.open_orders()
    open_orders_check_ok = bool(
        isinstance(open_orders_response, dict)
        and open_orders_response.get("success") is True
    )
    open_orders = get_result(open_orders_response)
    if not isinstance(open_orders, list):
        open_orders = []

    closed_orders_response = api.closed_orders()
    closed_orders_check_ok = bool(
        isinstance(closed_orders_response, dict)
        and closed_orders_response.get("success") is True
    )
    closed_orders = get_result(closed_orders_response)
    if not isinstance(closed_orders, list):
        closed_orders = []

    if not open_orders_check_ok:
        log("ORDER BLOCKED — open-order duplicate check failed.")
        return

    if not closed_orders_check_ok:
        log("ORDER BLOCKED — closed-order duplicate check failed.")
        return

    pending_orders = []

    for order in open_orders:
        try:
            order_product_id = int(order.get("product_id", PRODUCT_ID))
        except Exception:
            order_product_id = PRODUCT_ID

        if order_product_id != PRODUCT_ID:
            continue

        order_type = str(
            order.get("order_type", order.get("type", ""))
        ).lower()
        state = str(order.get("state", "")).lower()

        if "limit" in order_type and state not in [
            "cancelled", "filled", "rejected"
        ]:
            pending_orders.append(order)

    # Direction-change cleanup.
    cancel_failed = False
    position_close_failed = False

    for order in list(open_orders):
        order_id = order.get("id")
        order_side = str(order.get("side", "")).lower()

        if order_side != opposite_side or order_id is None:
            continue

        cancel_result = api.cancel_order(order_id)

        if (
            isinstance(cancel_result, dict)
            and cancel_result.get("success")
        ):
            log(
                f"OLD {order_side.upper()} ORDER CANCELLED — "
                f"SuperTrend changed to {signal_direction}."
            )
        else:
            cancel_failed = True
            log("OLD OPPOSITE ORDER CANCEL FAILED — NEW ORDER BLOCKED.")

    if not cancel_failed:
        cleanup_position_response = api.position()
        cleanup_position_ok = bool(
            isinstance(cleanup_position_response, dict)
            and cleanup_position_response.get("success") is True
        )

        if not cleanup_position_ok:
            position_close_failed = True
            log("POSITION CHECK FAILED — NEW ORDER BLOCKED.")
        else:
            cleanup_position_data = get_result(cleanup_position_response)

            if isinstance(cleanup_position_data, list):
                cleanup_position = (
                    cleanup_position_data[0] if cleanup_position_data else {}
                )
            elif isinstance(cleanup_position_data, dict):
                cleanup_position = cleanup_position_data
            else:
                cleanup_position = {}

            cleanup_position_size = number(
                cleanup_position.get("size"), 0
            )

            opposite_position_exists = (
                (signal_direction == "BUY" and cleanup_position_size < 0)
                or
                (signal_direction == "SELL" and cleanup_position_size > 0)
            )

            if opposite_position_exists:
                close_side = "buy" if cleanup_position_size < 0 else "sell"
                close_size = abs(int(cleanup_position_size))

                if close_size <= 0:
                    position_close_failed = True
                    log("OPPOSITE POSITION SIZE INVALID — NEW ORDER BLOCKED.")
                else:
                    close_result = api.place_market_reduce_only(
                        side=close_side,
                        size=close_size,
                        client_order_id=(
                            f"STB_CLOSE_{signal_direction}_{int(time.time())}"
                        )
                    )

                    if (
                        isinstance(close_result, dict)
                        and close_result.get("success")
                    ):
                        log(
                            f"OLD OPPOSITE POSITION CLOSED/REDUCED — "
                            f"{abs(cleanup_position_size)} contracts."
                        )
                        record_event("TRADE", f"Opposite position closed/reduced — {abs(cleanup_position_size)} contracts.")
                    else:
                        position_close_failed = True
                        log(
                            "OPPOSITE POSITION CLOSE/REDUCE FAILED — "
                            "NEW ORDER BLOCKED."
                        )

    if cancel_failed or position_close_failed:
        return

    refreshed_open_response = api.open_orders()
    refreshed_open_ok = bool(
        isinstance(refreshed_open_response, dict)
        and refreshed_open_response.get("success") is True
    )

    if not refreshed_open_ok:
        log("OPEN-ORDER VERIFICATION FAILED — NEW ORDER BLOCKED.")
        return

    refreshed_open_orders = get_result(refreshed_open_response)
    if not isinstance(refreshed_open_orders, list):
        refreshed_open_orders = []

    for order in refreshed_open_orders:
        if str(order.get("side", "")).lower() == opposite_side:
            log(
                "OLD OPPOSITE ENTRY/TP ORDER IS STILL OPEN — "
                "NEW ORDER BLOCKED."
            )
            return

    final_position_response = api.position()
    final_position_ok = bool(
        isinstance(final_position_response, dict)
        and final_position_response.get("success") is True
    )

    if not final_position_ok:
        log("FINAL POSITION VERIFICATION FAILED — NEW ORDER BLOCKED.")
        return

    final_position_data = get_result(final_position_response)

    if isinstance(final_position_data, list):
        final_position = (
            final_position_data[0] if final_position_data else {}
        )
    elif isinstance(final_position_data, dict):
        final_position = final_position_data
    else:
        final_position = {}

    final_position_size = number(final_position.get("size"), 0)

    opposite_position_remaining = (
        (signal_direction == "BUY" and final_position_size < 0)
        or
        (signal_direction == "SELL" and final_position_size > 0)
    )

    if opposite_position_remaining:
        log(
            "OLD OPPOSITE POSITION IS STILL OPEN — "
            "NEW ORDER BLOCKED FOR SAFETY."
        )
        return

    # Exact stable signal ID protection.
    stable_prefix = f"STB_{signal_direction}_{signal_candle_epoch}"

    same_direction_open = any(
        str(order.get("side", "")).lower() == order_side
        for order in pending_orders
    )

    if same_direction_open:
        log(
            f"DUPLICATE BLOCKED — existing {signal_direction} "
            "LIMIT order is already open."
        )
        return

    same_signal_already_seen = any(
        str(order.get("client_order_id", "")).startswith(stable_prefix)
        for order in pending_orders + closed_orders
    )

    if same_signal_already_seen:
        log(
            f"DUPLICATE BLOCKED — {signal_direction} signal "
            "was already processed."
        )
        return

    bot_history = []

    for order in closed_orders:
        try:
            product_id = int(order.get("product_id", PRODUCT_ID))
        except Exception:
            product_id = PRODUCT_ID

        if product_id != PRODUCT_ID:
            continue

        client_id = str(order.get("client_order_id", ""))

        if (
            client_id.startswith("STB_")
            or client_id.startswith("ST_BUY_")
            or client_id.startswith("ST_SELL_")
        ):
            bot_history.append(order)

    def order_sort_key(order):
        for key in ("created_at_ts", "created_at", "id"):
            value = order.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except Exception:
                continue
        return 0

    bot_history.sort(key=order_sort_key, reverse=True)

    last_bot_direction = ""

    if bot_history:
        latest_bot = bot_history[0]
        latest_client_id = str(latest_bot.get("client_order_id", ""))

        if latest_client_id.startswith("STB_BUY_"):
            last_bot_direction = "BUY"
        elif latest_client_id.startswith("STB_SELL_"):
            last_bot_direction = "SELL"

    if last_bot_direction == signal_direction:
        log(
            f"SAME-DIRECTION BLOCKED — previous bot order was "
            f"also {signal_direction}."
        )
        return

    position_guard_response = api.position()
    position_guard_ok = bool(
        isinstance(position_guard_response, dict)
        and position_guard_response.get("success") is True
    )

    if not position_guard_ok:
        log("POSITION CHECK FAILED — NEW ORDER BLOCKED.")
        return

    position_guard_data = get_result(position_guard_response)

    if isinstance(position_guard_data, list):
        guard_position = position_guard_data[0] if position_guard_data else {}
    elif isinstance(position_guard_data, dict):
        guard_position = position_guard_data
    else:
        guard_position = {}

    guard_size = number(guard_position.get("size"), 0)

    same_direction_position = (
        (signal_direction == "BUY" and guard_size > 0)
        or
        (signal_direction == "SELL" and guard_size < 0)
    )

    if same_direction_position:
        log(
            f"POSITION BLOCKED — existing {signal_direction} "
            "position is already live."
        )
        return

    basket_results = []
    all_baskets_ok = True

    for basket_name, basket_qty, basket_tp in target_baskets:
        client_id = f"{stable_prefix}_{basket_name}"

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
            log(
                f"{basket_name} FAILED: "
                f"{result.get('error', 'Unknown error')}"
            )
            break

        result_data = result.get("result", {})
        result_id = (
            result_data.get("id")
            if isinstance(result_data, dict)
            else "-"
        )

        log(
            f"{basket_name} ACCEPTED — "
            f"{signal_direction} LIMIT={limit_entry_price} "
            f"QTY={basket_qty} TP={basket_tp} ID={result_id}"
        )

    if not all_baskets_ok:
        for item in basket_results:
            accepted = item.get("result", {})
            accepted_data = accepted.get("result", {})
            accepted_id = (
                accepted_data.get("id")
                if isinstance(accepted_data, dict)
                else None
            )

            if accepted_id is not None:
                api.cancel_order(accepted_id)

        log(
            "PARTIAL BASKET FAILURE — accepted baskets were cancelled."
        )
        record_event("ERROR", f"{signal_direction} basket partially failed; accepted baskets cancelled.")
        return

    log(
        f"SUCCESS — {len(basket_results)} REAL "
        f"{signal_direction} LIMIT BASKET(S) SENT."
    )
    record_event(
        signal_direction,
        f"{signal_direction} trade order sent — {len(basket_results)} basket(s), "
        f"entry {limit_entry_price}, qty {DEFAULT_ORDER_SIZE} contracts.",
        {"price": limit_entry_price, "qty": DEFAULT_ORDER_SIZE, "signal_candle": signal_candle_epoch}
    )

# ============================================================
# MAIN LOOP
# ============================================================


# ============================================================
# EMBEDDED BACKGROUND TRADING WORKER
# 1-MINUTE + SUPERVISOR RECOVERY + SINGLE-WORKER LOCK
# ============================================================
# The dashboard is only the monitoring layer.  The background worker is the
# single live order executor.  This block does NOT change the trading rules;
# it only controls how the existing worker is kept alive inside this process.

BACKGROUND_WORKER_ACTIVE = True

import threading
import traceback

_WORKER_STATE_LOCK = threading.Lock()
_WORKER_THREAD = None
_WORKER_STOP_EVENT = None
_WORKER_LOCK_ACQUIRED = False


def _worker_credentials():
    worker_key = globals().get("OWNER_API_KEY", "") or os.getenv("OWNER_API_KEY", "")
    worker_secret = globals().get("OWNER_API_SECRET", "") or os.getenv("OWNER_API_SECRET", "")
    return worker_key, worker_secret


def _worker_loop(worker_key, worker_secret, stop_event):
    """Run the existing trading cycle forever until the process is stopped."""
    global API_KEY, API_SECRET
    API_KEY = worker_key
    API_SECRET = worker_secret

    worker_api = _EmbeddedWorkerDeltaAPI(worker_key, worker_secret)
    last_cycle_bucket = None

    while not stop_event.is_set():
        try:
            bucket = int(time.time()) // CANDLE_SECONDS

            # Exactly one cycle per completed 1-minute bucket.
            if bucket != last_cycle_bucket:
                last_cycle_bucket = bucket
                _embedded_worker_cycle(
                    worker_api,
                    worker_key,
                    worker_secret
                )

        except Exception as exc:
            # A cycle error must not kill the worker thread.
            log(f"BACKGROUND WORKER CYCLE ERROR: {exc!r}")
            try:
                traceback.print_exc()
            except Exception:
                pass

        # Small sleep keeps CPU usage low and checks the stop/recovery state.
        stop_event.wait(2)


def _worker_supervisor():
    """Keep exactly one worker alive; restart it if the worker thread dies."""
    global _WORKER_THREAD, _WORKER_STOP_EVENT, _WORKER_LOCK_ACQUIRED

    worker_key, worker_secret = _worker_credentials()

    if not worker_key or not worker_secret:
        log("BACKGROUND WORKER NOT STARTED — OWNER API credentials missing.")
        return

    # Process-level file lock: prevents a second worker process from trading
    # from the same Streamlit environment where OS file locking is available.
    try:
        _WORKER_LOCK_ACQUIRED = acquire_worker_lock()
    except Exception as exc:
        _WORKER_LOCK_ACQUIRED = False
        log(f"BACKGROUND WORKER LOCK ERROR: {exc!r}")

    if not _WORKER_LOCK_ACQUIRED:
        log("BACKGROUND WORKER NOT STARTED — another worker owns the lock.")
        return

    try:
        write_pid()
    except Exception:
        pass

    supervisor_thread = threading.current_thread()
    log(
        f"BACKGROUND WORKER SUPERVISOR ACTIVE — PID={os.getpid()} "
        f"TIMEFRAME={TIMEFRAME} CANDLE_SECONDS={CANDLE_SECONDS}"
    )

    while True:
        try:
            with _WORKER_STATE_LOCK:
                current = _WORKER_THREAD

            # Start the worker when missing or restart it after an unexpected
            # worker-thread death.  This is automatic thread-level recovery.
            if current is None or not current.is_alive():
                stop_event = threading.Event()
                thread = threading.Thread(
                    target=_worker_loop,
                    args=(worker_key, worker_secret, stop_event),
                    name="delta-background-trading-worker",
                    daemon=True
                )

                with _WORKER_STATE_LOCK:
                    _WORKER_STOP_EVENT = stop_event
                    _WORKER_THREAD = thread

                thread.start()
                log("BACKGROUND WORKER STARTED / RESTARTED")

            time.sleep(2)

        except Exception as exc:
            # Supervisor itself should keep trying unless the whole Python
            # process has been terminated by the hosting platform.
            log(f"WORKER SUPERVISOR ERROR: {exc!r}")
            time.sleep(2)


def _start_embedded_background_worker():
    """Start one supervisor per Python process using Streamlit's resource cache."""
    try:
        # Streamlit resource caching gives a process-wide singleton across
        # normal reruns/sessions, avoiding a new supervisor on every rerun.
        @st.cache_resource(show_spinner=False)
        def _get_supervisor():
            supervisor = threading.Thread(
                target=_worker_supervisor,
                name="delta-background-worker-supervisor",
                daemon=True
            )
            supervisor.start()
            return supervisor

        supervisor = _get_supervisor()
        return supervisor

    except Exception as exc:
        log(f"FAILED TO START WORKER SUPERVISOR: {exc!r}")
        return None


# ============================================================
# 5-MINUTE STREAMLIT SELF-PING / KEEP-ALIVE
# ============================================================
# The URL is intentionally read from an environment variable or Streamlit
# Secret so the real app URL does not need to be hard-coded in source code.
KEEP_ALIVE_INTERVAL_SECONDS = 300
KEEP_ALIVE_TIMEOUT_SECONDS = 20
DEFAULT_STREAMLIT_APP_URL = "https://delta-futures-appuction-bot-eubkvtjunebqpahvqy9cuz.streamlit.app"


def _keep_alive_url():
    url = os.getenv("STREAMLIT_APP_URL", "").strip()
    if url:
        return url.rstrip("/")

    try:
        secret_url = str(st.secrets.get("STREAMLIT_APP_URL", "")).strip()
        if secret_url:
            return secret_url.rstrip("/")
    except Exception:
        pass

    return DEFAULT_STREAMLIT_APP_URL.rstrip("/")


def _keep_alive_loop():
    """Ping this Streamlit app every 5 minutes while this process is alive."""
    url = _keep_alive_url()

    if not url:
        log(
            "KEEP-ALIVE NOT STARTED — STREAMLIT_APP_URL is missing. "
            "Set STREAMLIT_APP_URL to the app's https://...streamlit.app URL."
        )
        return

    log(f"KEEP-ALIVE ACTIVE — pinging {url} every {KEEP_ALIVE_INTERVAL_SECONDS}s")

    while True:
        try:
            response = requests.get(
                url,
                timeout=KEEP_ALIVE_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": "Delta-Trading-Dashboard-KeepAlive/1.0"
                }
            )
            log(
                f"KEEP-ALIVE PING OK — HTTP {response.status_code} "
                f"URL={url}"
            )
        except Exception as exc:
            # A failed ping must never stop the trading worker.
            log(f"KEEP-ALIVE PING ERROR: {exc!r}")

        time.sleep(KEEP_ALIVE_INTERVAL_SECONDS)


def _start_keep_alive():
    """Start exactly one keep-alive thread per Python process."""
    try:
        @st.cache_resource(show_spinner=False)
        def _get_keep_alive_thread():
            thread = threading.Thread(
                target=_keep_alive_loop,
                name="streamlit-self-keep-alive",
                daemon=True
            )
            thread.start()
            return thread

        return _get_keep_alive_thread()

    except Exception as exc:
        log(f"FAILED TO START KEEP-ALIVE: {exc!r}")
        return None


# Make the embedded worker the single live order executor.
BACKGROUND_WORKER_ACTIVE = True

st.divider()
st.subheader("🤖 BACKGROUND TRADING WORKER")
st.success(
    "🟢 1-MINUTE BACKGROUND WORKER ACTIVE — "
    "Dashboard बंद/छोड़ने पर भी worker इसी Streamlit process में चलता रहेगा।"
)
st.caption(
    "Automatic thread recovery + single-worker lock enabled. "
    "यदि Streamlit Cloud पूरा Python process sleep/restart/terminate करता है, "
    "तो in-process worker भी उसी समय रुक जाएगा; process वापस आने पर worker फिर शुरू होगा।"
)

_start_embedded_background_worker()
_start_keep_alive()

# ============================================================
# AUTO REFRESH
# ============================================================
time.sleep(REFRESH_SECONDS)
st.rerun()

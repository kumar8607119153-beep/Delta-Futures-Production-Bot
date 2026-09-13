# ============================================================
# SANJAY RANA - DELTA REAL TRADING DASHBOARD
# PART 1/4
# ============================================================

import os
import time
import json
import hmac
import hashlib
import inspect
import threading
import websocket
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

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

REFRESH_SECONDS = 1
# ============================================================
# INDIAN TIME FUNCTION (इसे सबसे ऊपर रखें)
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


def show_price(val):
    try:
        if val is None or pd.isna(val):
            return "-"
        return f"${float(val):,.2f}"
    except Exception:
        return str(val)

def number(val, default=0.0):
    try:
        if val is None or pd.isna(val):
            return default
        return float(val)
    except Exception:
        return default
        

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
    os.getenv("BUY_OFFSET", "-50")
)

DEFAULT_SELL_OFFSET = int(
    os.getenv("SELL_OFFSET", "50")
)

DEFAULT_ORDER_SIZE = int(
    os.getenv("ORDER_SIZE", "1")
)

# LIMIT pending रहने के बाद कितने seconds में MARKET करना है.
# 0 = automatic MARKET conversion बंद.
DEFAULT_LIMIT_TIMEOUT = int(
    os.getenv("LIMIT_TIMEOUT", "60")
)

TARGET_1 = int(os.getenv("TARGET_1", "300"))
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


# ============================================================
# MAIN TABS — WATCHLIST / TRADINGVIEW FULL SCREEN / DASHBOARD
# ============================================================
selected_tab = st.radio(
    "SELECT VIEW",
    ["Watchlist", "Demo Account", "TradingView Chart", "Trading Dashboard"],
    horizontal=True,
    key="main_view_tab"
)

if selected_tab == "Watchlist":
    st.title("📋 WATCHLIST (LIVE TICK & LOGOS)")

    st.markdown("""
    <style>
    .watch-card {
        border: 1px solid rgba(128,128,128,.30);
        border-radius: 12px;
        padding: 10px;
        margin-bottom: 10px;
        background: rgba(128,128,128,.08);
    }
    </style>
    """, unsafe_allow_html=True)

    components.html("""
    <div style="display:flex; flex-direction:column; gap:8px; width:100%;">
      <div class="watch-card">
        <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-single-quote.js" async>
        {"symbol":"BINANCE:BTCUSDT","width":"100%","colorTheme":"dark","isTransparent":true,"locale":"en"}
        </script>
      </div>
      <div class="watch-card">
        <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-single-quote.js" async>
        {"symbol":"BINANCE:ETHUSDT","width":"100%","colorTheme":"dark","isTransparent":true,"locale":"en"}
        </script>
      </div>
      <div class="watch-card">
        <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-single-quote.js" async>
        {"symbol":"BINANCE:TAOUSDT","width":"100%","colorTheme":"dark","isTransparent":true,"locale":"en"}
        </script>
      </div>
      <div class="watch-card">
        <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-single-quote.js" async>
        {"symbol":"OANDA:XAUUSD","width":"100%","colorTheme":"dark","isTransparent":true,"locale":"en"}
        </script>
      </div>
    </div>
    """, height=520, scrolling=False)

    st.stop()
    

# ============================================================
# ============================================================
# DEMO ACCOUNT — MIRROR OF THE REAL ENGINE
# IMPORTANT:
# - Demo uses the SAME global df produced by the real engine.
# - Demo does NOT fetch candles.
# - Demo does NOT calculate SuperTrend.
# - Demo does NOT place real/exchange orders.
# - Only the Demo account logic/UI lives in this block.
# ============================================================

DEMO_QTY = 0.01
DEMO_TP1_QTY = 0.005
DEMO_TP2_QTY = 0.003
DEMO_TP3_QTY = 0.002


def _demo_close_time(bar_time):
    """Closed 5-minute candle's close time."""
    return int(bar_time) + CANDLE_SECONDS


def _demo_trade_id(history):
    """Return the next TRADE #xxx id without any artificial history cap."""
    highest = 0
    for trade in history:
        try:
            tid = str(trade.get("Trade ID", ""))
            if tid.startswith("TRADE #"):
                highest = max(highest, int(tid.replace("TRADE #", "")))
        except Exception:
            continue
    return f"TRADE #{highest + 1:03d}"


def _demo_new_trade(side, bar_time, entry_price, history):
    """Create one grouped Trade History Block."""
    entry_price = float(entry_price)
    side = str(side).upper()

    if side == "BUY":
        t1 = entry_price + TARGET_1
        t2 = entry_price + TARGET_2
        t3 = entry_price + TARGET_3
    else:
        t1 = entry_price - TARGET_1
        t2 = entry_price - TARGET_2
        t3 = entry_price - TARGET_3

    return {
        "Trade ID": _demo_trade_id(history),
        "Signal Time": indian_time(_demo_close_time(bar_time)),
        "Side": side,
        "Entry Time": indian_time(_demo_close_time(bar_time)),
        "Entry Price": round(entry_price, 2),
        "Quantity": DEMO_QTY,
        "TP1 Price": round(t1, 2),
        "TP1 Time": "-",
        "TP1 Qty": DEMO_TP1_QTY,
        "TP1 Status": "PENDING",
        "TP2 Price": round(t2, 2),
        "TP2 Time": "-",
        "TP2 Qty": DEMO_TP2_QTY,
        "TP2 Status": "PENDING",
        "TP3 Price": round(t3, 2),
        "TP3 Time": "-",
        "TP3 Qty": DEMO_TP3_QTY,
        "TP3 Status": "PENDING",
        "Remaining Qty": DEMO_QTY,
        "Exit Price": "-",
        "Exit Time": "-",
        "Exit Qty": "-",
        "Exit Reason": "-",
        "Realized P&L": 0.0,
        "_tp1_hit": False,
        "_tp2_hit": False,
        "_tp3_hit": False,
        "_closed": False,
    }


def _demo_add_pnl(trade, price, qty):
    """Add realized P&L for a target/exit using the demo entry price."""
    entry = float(trade["Entry Price"])
    price = float(price)
    qty = float(qty)
    if trade["Side"] == "BUY":
        pnl = (price - entry) * qty
    else:
        pnl = (entry - price) * qty
    trade["Realized P&L"] = round(float(trade["Realized P&L"]) + pnl, 2)


def _demo_process_targets(trade, bar_time, high, low):
    """Process TP touches on a confirmed candle. Returns True when TP3 closes trade."""
    if trade is None or trade.get("_closed"):
        return False

    side = trade["Side"]
    close_time = indian_time(_demo_close_time(bar_time))
    high = float(high)
    low = float(low)

    t1 = float(trade["TP1 Price"])
    t2 = float(trade["TP2 Price"])
    t3 = float(trade["TP3 Price"])

    hit1 = (side == "BUY" and high >= t1) or (side == "SELL" and low <= t1)
    hit2 = (side == "BUY" and high >= t2) or (side == "SELL" and low <= t2)
    hit3 = (side == "BUY" and high >= t3) or (side == "SELL" and low <= t3)

    if not trade["_tp1_hit"] and hit1:
        trade["_tp1_hit"] = True
        trade["TP1 Time"] = close_time
        trade["TP1 Status"] = "HIT"
        trade["Remaining Qty"] = max(0.0, float(trade["Remaining Qty"]) - DEMO_TP1_QTY)
        _demo_add_pnl(trade, t1, DEMO_TP1_QTY)

    if not trade["_tp2_hit"] and hit2:
        trade["_tp2_hit"] = True
        trade["TP2 Time"] = close_time
        trade["TP2 Status"] = "HIT"
        trade["Remaining Qty"] = max(0.0, float(trade["Remaining Qty"]) - DEMO_TP2_QTY)
        _demo_add_pnl(trade, t2, DEMO_TP2_QTY)

    if not trade["_tp3_hit"] and hit3:
        trade["_tp3_hit"] = True
        trade["TP3 Time"] = close_time
        trade["TP3 Status"] = "HIT / COMPLETED"
        trade["Remaining Qty"] = max(0.0, float(trade["Remaining Qty"]) - DEMO_TP3_QTY)
        _demo_add_pnl(trade, t3, DEMO_TP3_QTY)
        trade["_closed"] = True
        return True

    return False


def _demo_close_reversal(trade, bar_time, price, new_signal):
    """Close remaining quantity at the opposite confirmed signal candle close."""
    if trade is None or trade.get("_closed"):
        return

    remaining = float(trade.get("Remaining Qty", 0))
    if remaining <= 0:
        trade["_closed"] = True
        return

    price = float(price)
    trade["Exit Price"] = round(price, 2)
    trade["Exit Time"] = indian_time(_demo_close_time(bar_time))
    trade["Exit Qty"] = remaining
    trade["Exit Reason"] = f"OPPOSITE SUPERTREND REVERSAL ({str(new_signal).upper()})"
    _demo_add_pnl(trade, price, remaining)
    trade["Remaining Qty"] = 0
    trade["_closed"] = True


def _demo_rebuild_history(df_shared):
    """Reconstruct real demo Trade Blocks from the shared Real-engine df."""
    history = []
    active = None

    work = df_shared.reset_index(drop=True).copy()
    if work.empty or "SIGNAL" not in work.columns:
        return history, active

    for i in range(len(work)):
        row = work.iloc[i]
        bar_time = int(row["time"])
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        signal = str(row.get("SIGNAL", "") or "").upper()

        if active is not None:
            _demo_process_targets(active, bar_time, high, low)
            if active.get("_closed"):
                history.append(active)
                active = None

        if signal in ("BUY", "SELL"):
            if active is not None:
                if active["Side"] != signal:
                    _demo_close_reversal(active, bar_time, close, signal)
                    history.append(active)
                    active = None
                else:
                    # Same-direction signal does not create another trade.
                    continue

            active = _demo_new_trade(signal, bar_time, close, history)

    return history, active


def _demo_history_display_rows(history):
    """Hide internal flags while keeping each trade as one grouped block."""
    public = []
    for trade in history:
        public.append({
            "Trade ID": trade.get("Trade ID"),
            "Signal Time": trade.get("Signal Time"),
            "Side": trade.get("Side"),
            "Entry Time": trade.get("Entry Time"),
            "Entry Price": trade.get("Entry Price"),
            "Quantity": trade.get("Quantity"),
            "TP1 Price": trade.get("TP1 Price"),
            "TP1 Time": trade.get("TP1 Time"),
            "TP1 Qty": trade.get("TP1 Qty"),
            "TP1 Status": trade.get("TP1 Status"),
            "TP2 Price": trade.get("TP2 Price"),
            "TP2 Time": trade.get("TP2 Time"),
            "TP2 Qty": trade.get("TP2 Qty"),
            "TP2 Status": trade.get("TP2 Status"),
            "TP3 Price": trade.get("TP3 Price"),
            "TP3 Time": trade.get("TP3 Time"),
            "TP3 Qty": trade.get("TP3 Qty"),
            "TP3 Status": trade.get("TP3 Status"),
            "Remaining Qty": trade.get("Remaining Qty"),
            "Exit Price": trade.get("Exit Price"),
            "Exit Time": trade.get("Exit Time"),
            "Exit Qty": trade.get("Exit Qty"),
            "Exit Reason": trade.get("Exit Reason"),
            "Realized P&L": trade.get("Realized P&L"),
        })
    return public


def run_demo_account(df_shared):
    """Demo account only. Signal source is the already-calculated Real-engine df."""
    if "demo_history" not in st.session_state:
        st.session_state.demo_history = []
    if "demo_position" not in st.session_state:
        st.session_state.demo_position = None
    if "demo_last_processed_bar" not in st.session_state:
        st.session_state.demo_last_processed_bar = None
    if "demo_history_initialized" not in st.session_state:
        st.session_state.demo_history_initialized = False

    st.title("🟢 DEMO ACCOUNT (AUTO-TRADING)")
    st.caption("Exact Mirror: Real engine confirmed SuperTrend signal → Demo CLOSE-price entry")

    if df_shared is None or df_shared.empty or "SIGNAL" not in df_shared.columns:
        st.error("Real engine ka shared df / confirmed SIGNAL available nahi hai.")
        return

    work = df_shared.reset_index(drop=True).copy()
    current_start = (int(time.time()) // CANDLE_SECONDS) * CANDLE_SECONDS
    work = work[work["time"] < current_start].reset_index(drop=True)

    if work.empty:
        st.error("Confirmed 5-minute candles available nahi hain.")
        return

    # First open/restart: reconstruct from the complete history present in the shared df.
    if not st.session_state.demo_history_initialized:
        rebuilt, active = _demo_rebuild_history(work)
        st.session_state.demo_history = rebuilt
        st.session_state.demo_position = active
        st.session_state.demo_history_initialized = True
        st.session_state.demo_last_processed_bar = int(work.iloc[-1]["time"])

    last = work.iloc[-1]
    last_bar_time = int(last["time"])
    last_close = float(last["close"])
    last_high = float(last["high"])
    last_low = float(last["low"])
    last_signal = str(last.get("SIGNAL", "") or "").upper()

    # Process only a newly closed confirmed candle on subsequent reruns.
    if st.session_state.demo_last_processed_bar != last_bar_time:
        st.session_state.demo_last_processed_bar = last_bar_time

        pos = st.session_state.demo_position
        if pos is not None:
            _demo_process_targets(pos, last_bar_time, last_high, last_low)
            if pos.get("_closed"):
                st.session_state.demo_history.append(pos)
                st.session_state.demo_position = None
                pos = None

        if last_signal in ("BUY", "SELL"):
            pos = st.session_state.demo_position
            if pos is not None:
                if pos["Side"] != last_signal:
                    _demo_close_reversal(pos, last_bar_time, last_close, last_signal)
                    st.session_state.demo_history.append(pos)
                    st.session_state.demo_position = None
                else:
                    # Same-direction flip cannot create another Demo trade block.
                    pos = None

            if st.session_state.demo_position is None:
                st.session_state.demo_position = _demo_new_trade(
                    last_signal,
                    last_bar_time,
                    last_close,
                    st.session_state.demo_history,
                )

    pos = st.session_state.demo_position

    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SIGNAL SOURCE", "REAL ENGINE df")
    c2.metric("LAST CLOSED 5M PRICE", show_price(last_close))
    c3.metric("CONFIRMED SIGNAL", last_signal or "NO NEW FLIP")
    c4.metric("TRADE BLOCKS", len(st.session_state.demo_history) + (1 if pos else 0))

    if pos:
        st.success(
            f"OPEN {pos['Trade ID']} — {pos['Side']} — "
            f"Entry {show_price(pos['Entry Price'])} — "
            f"Remaining {pos['Remaining Qty']}"
        )
        st.write(
            f"TP1: **{show_price(pos['TP1 Price'])}** — {pos['TP1 Status']} | "
            f"TP2: **{show_price(pos['TP2 Price'])}** — {pos['TP2 Status']} | "
            f"TP3: **{show_price(pos['TP3 Price'])}** — {pos['TP3 Status']}"
        )
    else:
        st.info("No active Demo trade. Next confirmed opposite/new SuperTrend flip ka wait hai.")

    st.subheader("📜 DEMO TRADE HISTORY — GROUPED TRADE BLOCKS")
    rows = _demo_history_display_rows(st.session_state.demo_history)
    if pos:
        rows.append(_demo_history_display_rows([pos])[0])

    if rows:
        df_history = pd.DataFrame(rows)
        total_pnl = float(df_history["Realized P&L"].sum()) if "Realized P&L" in df_history.columns else 0.0
        h1, h2 = st.columns(2)
        h1.metric("TRADE BLOCKS", len(rows))
        # Period is calculated from the oldest to newest confirmed 5-minute candle
        # currently available in the same shared Real-engine dataframe.
        first_history_time = int(work.iloc[0]["time"])
        last_history_time = int(work.iloc[-1]["time"])
        period_days = max(1, int((last_history_time - first_history_time + 86399) // 86400))
        pnl_text = f"+${total_pnl:,.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):,.2f}"
        h2.metric(
            "TOTAL REALIZED P&L",
            f"{pnl_text} | {period_days} Days",
        )
        st.dataframe(df_history, use_container_width=True, hide_index=True)
    else:
        st.info("Historical demo trades nahi mile. Koi fake/dummy trade create nahi ki gayi.")

    st.caption(
        "Demo has no LIMIT/pending order and no separate candle/SuperTrend engine. "
        "Entry is the confirmed signal candle CLOSE; TP events use confirmed candle high/low; "
        "opposite signal exits remaining quantity at that signal candle CLOSE."
    )


# ------------------------------------------------------------
# TRADINGVIEW CHART — FULL AVAILABLE SCREEN
# Early Exit: नीचे का पूरा trading dashboard execute नहीं होगा.
# ------------------------------------------------------------
if selected_tab == "TradingView Chart":
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 0rem !important;
            padding-bottom: 0rem !important;
            padding-left: 0rem !important;
            padding-right: 0rem !important;
            max-width: 100% !important;
        }
        header[data-testid="stHeader"] {
            display: none;
        }
        [data-testid="stAppViewContainer"] > .main {
            padding: 0 !important;
        }
        iframe {
            width: 100% !important;
            border: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    components.html(
        """
        <div
            class="tradingview-widget-container"
            style="height:100vh;width:100%;margin:0;padding:0;">

            <div
                class="tradingview-widget-container__widget"
                style="height:100vh;width:100%;">
            </div>

            <script
                type="text/javascript"
                src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
                async>
            {
                "autosize": true,
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
        height=900,
        scrolling=False
    )

    st.stop()

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
# DELTA API
# ============================================================

# ============================================================
# LINE-BY-LINE DIAGNOSTIC (ADDED — ORIGINAL CODE PRESERVED)
# ============================================================
st.session_state["line_diagnostic"] = []

def _line_diag(step, status, detail=""):
    try:
        line_no = inspect.currentframe().f_back.f_lineno
    except Exception:
        line_no = 0
    st.session_state["line_diagnostic"].append({
        # LINE अब diagnostic serial number रहेगा: 1, 2, 3, 4...
        "line": len(st.session_state["line_diagnostic"]) + 1,
        # Original source-code line को अलग रखा गया है; dashboard में serial दिखेगा।
        "source_line": line_no,
        "step": str(step),
        "status": str(status),
        "detail": str(detail)
    })

class DeltaAPI:

    def __init__(self, api_key=None, api_secret=None):
        self.api_key = str(api_key or "").strip()
        self.api_secret = str(api_secret or "").strip()

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

        # ADDED: keep the exact locally signed string for comparison with Delta.
        st.session_state["last_signature_message"] = message

        _line_diag(
            "SIGNATURE MESSAGE",
            "PASSED",
            f"{method.upper()}{timestamp}{path}{query_string}{body}"
        )

        return hmac.new(
            self.api_secret.encode("utf-8"),
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
            query_string = "?" + urlencode(params, doseq=True)


        headers = {
            "Accept": "application/json",
            "User-Agent": "Sanjay-Rana-Real-Trading-Bot"
        }


        if private:

            if not self.api_key or not self.api_secret:

                return {
                    "success": False,
                    "error": "API key/secret missing"
                }


            timestamp = str(
                int(time.time())
            )

            _line_diag(
                "TIMESTAMP",
                "PASSED",
                f"timestamp={timestamp}"
            )

            signature = self.make_signature(
                method,
                timestamp,
                path,
                query_string,
                payload
            )

            # ADDED: retain the exact generated HMAC for the bottom diagnostic panel.
            st.session_state["last_generated_signature"] = signature
            st.session_state["last_request_method"] = method.upper()
            st.session_state["last_request_path"] = path
            st.session_state["last_request_query"] = query_string
            st.session_state["last_request_payload"] = payload


            headers.update({
                "api-key": self.api_key,
                "timestamp": timestamp,
                "signature": signature,
                "Content-Type": "application/json"
            })

            _line_diag(
                "HEADERS / SIGNATURE",
                "PASSED",
                f"api_key=****{self.api_key[-4:] if self.api_key else ''} | signature={signature} | base_url={BASE_URL}"
            )


        try:

            # ============================================================
            # ADDED: ACTUAL AUTHENTICATION CONSISTENCY CHECK
            # This diagnostic is PRIVATE-request only so public requests
            # do not try to use an undefined timestamp.
            # ============================================================
            if private:
                try:
                    _recomputed_signature = hmac.new(
                        self.api_secret.encode("utf-8"),
                        (
                            method.upper()
                            + timestamp
                            + path
                            + query_string
                            + payload
                        ).encode("utf-8"),
                        hashlib.sha256
                    ).hexdigest()

                    _signature_same = (
                        _recomputed_signature == headers.get("signature", "")
                    )
                    _timestamp_same = (
                        str(headers.get("timestamp", "")) == str(timestamp)
                    )
                    _key_same = (
                        str(headers.get("api-key", "")) == str(self.api_key)
                    )
                    _body_hash = hashlib.sha256(
                        payload.encode("utf-8")
                    ).hexdigest() if payload else "EMPTY"
                    _secret_fingerprint = hashlib.sha256(
                        self.api_secret.encode("utf-8")
                    ).hexdigest()[:16] if self.api_secret else "EMPTY"

                    _line_diag(
                        "ACTUAL AUTH CHECK",
                        "PASSED" if (_signature_same and _timestamp_same and _key_same) else "FAILED",
                        (
                            f"signature_header_matches_recomputed={_signature_same} | "
                            f"timestamp_header_matches_signed_timestamp={_timestamp_same} | "
                            f"api_key_header_matches_loaded_key={_key_same} | "
                            f"secret_fingerprint={_secret_fingerprint} | "
                            f"body_sha256={_body_hash} | "
                            f"header_timestamp={headers.get('timestamp', '')} | "
                            f"signed_timestamp={timestamp}"
                        )
                    )
                except Exception as _auth_check_error:
                    _line_diag(
                        "ACTUAL AUTH CHECK",
                        "FAILED",
                        f"Authentication consistency check error: {_auth_check_error}"
                    )

            _line_diag(
                "DELTA API REQUEST",
                "RUNNING",
                f"{method.upper()} {BASE_URL + path} | query={query_string or '(empty)'} | payload={payload or '(empty)'}"
            )

            response = self.session.request(
                method.upper(),
                BASE_URL + path,
                params=params,
                data=payload if payload else None,
                headers=headers,
                timeout=(3, 27)
            )

            # ADDED: record the request values actually prepared for this HTTP call.
            _line_diag(
                "ACTUAL REQUEST VALUES",
                "PASSED",
                (
                    f"method={method.upper()} | url={BASE_URL + path} | "
                    f"api_key=****{self.api_key[-4:] if self.api_key else ''} | "
                    f"timestamp={headers.get('timestamp', '')} | "
                    f"signature={headers.get('signature', '')} | "
                    f"content_type={headers.get('Content-Type', '')} | "
                    f"body_length={len(payload)}"
                )
            )

            _line_diag(
                "DELTA RESPONSE",
                "PASSED" if response.ok else "FAILED",
                f"HTTP {response.status_code} | {response.text[:1000]}"
            )

            try:
                data = response.json()

            except Exception:

                _line_diag(
                    "RESPONSE JSON",
                    "FAILED",
                    response.text[:1000]
                )

                return {
                    "success": False,
                    "error": response.text
                }

            # ============================================================
            # ADDED: EXACT LOCAL-vs-DELTA SIGNATURE COMPARISON
            # ============================================================
            try:
                delta_signature_data = ""
                if isinstance(data, dict):
                    delta_signature_data = str(
                        data.get("context", {}).get("signature_data", "")
                    )

                local_signature_data = str(
                    st.session_state.get("last_signature_message", "")
                )

                if delta_signature_data:
                    if local_signature_data == delta_signature_data:
                        _line_diag(
                            "EXACT SIGNATURE DATA COMPARE",
                            "PASSED",
                            "LOCAL signature_data == DELTA signature_data"
                        )
                    else:
                        first_diff = None
                        max_len = max(
                            len(local_signature_data),
                            len(delta_signature_data)
                        )
                        for idx in range(max_len):
                            local_char = local_signature_data[idx] if idx < len(local_signature_data) else "<END>"
                            delta_char = delta_signature_data[idx] if idx < len(delta_signature_data) else "<END>"
                            if local_char != delta_char:
                                first_diff = idx
                                break

                        if first_diff is None:
                            first_diff = min(
                                len(local_signature_data),
                                len(delta_signature_data)
                            )

                        start = max(0, first_diff - 40)
                        end_local = min(len(local_signature_data), first_diff + 80)
                        end_delta = min(len(delta_signature_data), first_diff + 80)

                        _line_diag(
                            "EXACT SIGNATURE DATA COMPARE",
                            "FAILED",
                            f"FIRST DIFFERENCE AT CHARACTER {first_diff} | LOCAL[{start}:{end_local}]={local_signature_data[start:end_local]!r} | DELTA[{start}:{end_delta}]={delta_signature_data[start:end_delta]!r}"
                        )
                else:
                    _line_diag(
                        "EXACT SIGNATURE DATA COMPARE",
                        "RUNNING",
                        "Delta response did not provide context.signature_data for comparison"
                    )
            except Exception as compare_error:
                _line_diag(
                    "EXACT SIGNATURE DATA COMPARE",
                    "FAILED",
                    f"Comparison exception: {compare_error}"
                )


            return data


        except Exception as e:

            _line_diag(
                "REQUEST EXCEPTION",
                "FAILED",
                str(e)
            )

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
            - (4320 * CANDLE_SECONDS)
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
    # PUBLIC TRADES — BUYER / SELLER VOLUME
    # --------------------------------------------------------

    def public_trades(self):
        return self.request(
            "GET",
            f"/v2/trades/{SYMBOL}"
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
    # PLACE LIMIT / MARKET / REDUCE-ONLY TARGET ORDER
    # --------------------------------------------------------

    def place_limit_order(
        self,
        side,
        size,
        limit_price,
        reduce_only=False,
        client_order_id=None
    ):
        body = {
            "product_id": PRODUCT_ID,
            "product_symbol": SYMBOL,
            "limit_price": str(limit_price),
            "size": int(size),
            "side": side,
            "order_type": "limit_order",
            "reduce_only": bool(reduce_only),
        }

        if client_order_id:
            body["client_order_id"] = str(client_order_id)[:32]

        return self.request(
            "POST",
            "/v2/orders",
            body=body,
            private=True
        )

    def get_order(self, order_id):
        return self.request(
            "GET",
            f"/v2/orders/{order_id}",
            private=True
        )

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

api = DeltaAPI(OWNER_KEY, OWNER_SECRET)



# ============================================================
# BASIC STATUS (PERMANENTLY LIVE)
# ============================================================

st.info(
    "⚡ LIVE TRADING MODE: PERMANENTLY ACTIVE"
)

if selected_tab != "Demo Account":
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
# TRUE RANGE
# ============================================================

prev_close = df["close"].shift(1)

tr1 = df["high"] - df["low"]

tr2 = (
    df["high"] - prev_close
).abs()

tr3 = (
    df["low"] - prev_close
).abs()

df["TR"] = pd.concat(
    [tr1, tr2, tr3],
    axis=1
).max(axis=1)


# ============================================================
# ATR 10 — WILDER RMA
# ============================================================

df["ATR"] = float("nan")

first_atr = (
    df["TR"]
    .iloc[:ATR_PERIOD]
    .mean()
)

df.loc[
    ATR_PERIOD - 1,
    "ATR"
] = first_atr


for i in range(
    ATR_PERIOD,
    len(df)
):

    previous_atr = df.loc[
        i - 1,
        "ATR"
    ]

    current_tr = df.loc[
        i,
        "TR"
    ]

    df.loc[
        i,
        "ATR"
    ] = (
        previous_atr * (ATR_PERIOD - 1)
        + current_tr
    ) / ATR_PERIOD


# ============================================================
# HL2
# ============================================================

df["HL2"] = (
    df["high"] + df["low"]
) / 2.0


# ============================================================
# SUPERTREND COLUMNS
# ============================================================

df["UP"] = float("nan")
df["DN"] = float("nan")
df["TREND"] = float("nan")
df["SUPERTREND"] = float("nan")
df["SIGNAL"] = ""


# ============================================================
# SUPERTREND CALCULATION
#
# ATR = 10
# MULTIPLIER = 3.0
# SOURCE = HL2
#
# TradingView direction:
# -1 = BULLISH / BUY
#  1 = BEARISH / SELL
# ============================================================

for i in range(len(df)):

    atr = df.loc[i, "ATR"]

    if pd.isna(atr):
        continue

    src = df.loc[i, "HL2"]

    upper_basic = (
        src + MULTIPLIER * atr
    )

    lower_basic = (
        src - MULTIPLIER * atr
    )


    # ========================================================
    # FIRST VALID BAR
    # ========================================================

    if i == ATR_PERIOD - 1:

        df.loc[i, "UP"] = upper_basic
        df.loc[i, "DN"] = lower_basic
        df.loc[i, "TREND"] = 1
        df.loc[i, "SUPERTREND"] = upper_basic

        continue


    # ========================================================
    # PREVIOUS VALUES
    # ========================================================

    previous_up = df.loc[
        i - 1,
        "UP"
    ]

    previous_dn = df.loc[
        i - 1,
        "DN"
    ]

    previous_trend = df.loc[
        i - 1,
        "TREND"
    ]

    previous_close = df.loc[
        i - 1,
        "close"
    ]


    if pd.isna(previous_up):
        previous_up = upper_basic

    if pd.isna(previous_dn):
        previous_dn = lower_basic

    if pd.isna(previous_trend):
        previous_trend = 1


    # ========================================================
    # LOWER BAND
    # ========================================================

    if (
        lower_basic > previous_dn
        or previous_close < previous_dn
    ):

        lower_band = lower_basic

    else:

        lower_band = previous_dn


    # ========================================================
    # UPPER BAND
    # ========================================================

    if (
        upper_basic < previous_up
        or previous_close > previous_up
    ):

        upper_band = upper_basic

    else:

        upper_band = previous_up


    # ========================================================
    # TREND
    # ========================================================

    trend = previous_trend

    close = df.loc[
        i,
        "close"
    ]


    if previous_trend == 1:

        if close > upper_band:
            trend = -1
        else:
            trend = 1

    else:

        if close < lower_band:
            trend = 1
        else:
            trend = -1


    # ========================================================
    # SAVE
    # ========================================================

    df.loc[i, "UP"] = upper_band

    df.loc[i, "DN"] = lower_band

    df.loc[i, "TREND"] = trend


    # ========================================================
    # SUPERTREND LINE
    # ========================================================

    if trend == -1:

        df.loc[
            i,
            "SUPERTREND"
        ] = lower_band

    else:

        df.loc[
            i,
            "SUPERTREND"
        ] = upper_band


    # ========================================================
    # SIGNAL
    # ========================================================

    if (
        trend == -1
        and previous_trend == 1
    ):

        df.loc[
            i,
            "SIGNAL"
        ] = "BUY"


    elif (
        trend == 1
        and previous_trend == -1
    ):

        df.loc[
            i,
            "SIGNAL"
        ] = "SELL"


# ============================================================
# SIGNAL HISTORY
# ============================================================

signal_rows = df[
    df["SIGNAL"].isin(
        ["BUY", "SELL"]
    )
].copy()


# ============================================================
# BUYER % / SELLER % — COLLECT TRADES CONTINUOUSLY
# ============================================================

# Public trades are collected on every 1-second dashboard refresh.
# The values are grouped by 5-minute candle and frozen only when
# a new confirmed SuperTrend signal appears.
if "buyer_seller_trade_buckets" not in st.session_state:
    st.session_state["buyer_seller_trade_buckets"] = {}

if "buyer_seller_seen_trades" not in st.session_state:
    st.session_state["buyer_seller_seen_trades"] = set()

if "signal_buyer_percent" not in st.session_state:
    st.session_state["signal_buyer_percent"] = 0.0

if "signal_seller_percent" not in st.session_state:
    st.session_state["signal_seller_percent"] = 0.0

if "buyer_seller_signal_time" not in st.session_state:
    st.session_state["buyer_seller_signal_time"] = None


class DeltaTradeCollector:

    def __init__(self, symbol):
        self.symbol = symbol
        self.lock = threading.Lock()
        self.buckets = {}
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return

        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )
        self.thread.start()

    def _run(self):

        while True:

            try:

                ws = websocket.WebSocketApp(
                    "wss://public-socket.india.delta.exchange",
                    on_open=self._on_open,
                    on_message=self._on_message
                )

                ws.run_forever(
                    ping_interval=20,
                    ping_timeout=10
                )

            except Exception:
                time.sleep(5)

    def _on_open(self, ws):

        ws.send(json.dumps({
            "type": "subscribe",
            "payload": {
                "channels": [
                    {
                        "name": "trades",
                        "symbols": [self.symbol]
                    }
                ]
            }
        }))

    def _on_message(self, ws, message):

        try:

            data = json.loads(message)

            if data.get("type") != "trades":
                return

            ts = float(data.get("t", 0))
            size = abs(float(data.get("s", 0)))
            role = str(data.get("r", "")).lower()

            if ts > 10_000_000_000:
                ts /= 1_000_000

            if ts <= 0 or size <= 0:
                return

            if role == "t":
                side = "BUY"
            elif role == "m":
                side = "SELL"
            else:
                return

            candle_time = int(ts // CANDLE_SECONDS) * CANDLE_SECONDS

            with self.lock:
                bucket = self.buckets.setdefault(
                    candle_time,
                    {"BUY": 0.0, "SELL": 0.0}
                )
                bucket[side] += size

        except Exception:
            pass

    def get_bucket(self, candle_time):

        with self.lock:
            bucket = self.buckets.get(
                candle_time,
                {"BUY": 0.0, "SELL": 0.0}
            )

            return {
                "BUY": float(bucket["BUY"]),
                "SELL": float(bucket["SELL"])
            }


@st.cache_resource
def get_delta_trade_collector(symbol):

    collector = DeltaTradeCollector(symbol)
    collector.start()
    return collector


trade_collector = get_delta_trade_collector(SYMBOL)

# Only a NEW confirmed SuperTrend signal can change the displayed values.
if len(signal_rows) >= 1:
    latest_signal = signal_rows.iloc[-1]
    latest_signal_time = int(latest_signal["time"])

    if True:
        current_candle_time = (int(time.time()) // CANDLE_SECONDS) * CANDLE_SECONDS
        bucket = trade_collector.get_bucket(current_candle_time)

        buy_volume = float(bucket.get("BUY", 0.0))
        sell_volume = float(bucket.get("SELL", 0.0))
        total_volume = buy_volume + sell_volume

        if total_volume > 0:
            st.session_state["signal_buyer_percent"] = (
                buy_volume / total_volume
            ) * 100.0
            st.session_state["signal_seller_percent"] = (
                sell_volume / total_volume
            ) * 100.0

        # Mark this signal as processed so the values stay frozen.
        st.session_state["buyer_seller_signal_time"] = latest_signal_time


# ============================================================
# CURRENT CANDLE
# ============================================================

last_candle = df.iloc[-1]

current_trend = int(
    last_candle["TREND"]
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
# ------------------------------------------------------------
# DEMO ACCOUNT TAB — USE THE SAME REAL-ENGINE df/SIGNALS
# Real order logic below is not executed when Demo is selected.
# ------------------------------------------------------------
if selected_tab == "Demo Account":
    run_demo_account(df)
    st.stop()

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
# NEW LIVE MARKET PRICE — TOP DISPLAY
# ============================================================

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


# ============================================================
# DISPLAY LIVE MARKET PRICE
# ============================================================

st.header("💰 LIVE MARKET PRICE")

st.metric(
    "BTCUSD",
    show_price(live_price)
)


# ============================================================
# BUYER / SELLER %
# ============================================================

st.markdown(
    f"""<div style="margin-top: 5px; margin-bottom: 15px; font-size: 22px; line-height: 1.55;">
    <div>5-Min Closed Candle Buyer %: <b>{closed_candle_buyer_percent:.2f}%</b></div>
    <div>5-Min Closed Candle Seller %: <b>{closed_candle_seller_percent:.2f}%</b></div>
    <hr style="margin: 8px 0; border: 0.5px solid #ddd;">
    <div>1-Min Closed Candle Buyer %: <b>{closed_candle_1m_buyer_percent:.2f}%</b></div>
    <div>1-Min Closed Candle Seller %: <b>{closed_candle_1m_seller_percent:.2f}%</b></div>
</div>""",
    unsafe_allow_html=True,
)


# ============================================================
# 5-MINUTE CLOSED CANDLE BUYER % / SELLER %
# ============================================================

closed_candle = df.iloc[-1]

candle_high = float(closed_candle["high"])
candle_low = float(closed_candle["low"])
candle_close = float(closed_candle["close"])

candle_range = candle_high - candle_low

if candle_range > 0:
    closed_candle_buyer_percent = (
        (candle_close - candle_low) / candle_range
    ) * 100.0

    closed_candle_seller_percent = (
        (candle_high - candle_close) / candle_range
    ) * 100.0
else:
    closed_candle_buyer_percent = 50.0
    closed_candle_seller_percent = 50.0


# ============================================================
# DISPLAY — 5-MIN CLOSED CANDLE %
# ============================================================





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

# Target/entry lifecycle state. Targets are created ONLY after the entry
# order is confirmed fully filled by Delta.
if "entry_order_id" not in st.session_state:
    st.session_state["entry_order_id"] = None
if "entry_order_side" not in st.session_state:
    st.session_state["entry_order_side"] = ""
if "entry_order_size" not in st.session_state:
    st.session_state["entry_order_size"] = 0
if "entry_fill_price" not in st.session_state:
    st.session_state["entry_fill_price"] = None
if "target_order_ids" not in st.session_state:
    st.session_state["target_order_ids"] = []
if "targets_placed_for_entry" not in st.session_state:
    st.session_state["targets_placed_for_entry"] = None

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

    order_size = st.number_input(
        "ORDER SIZE",
        min_value=1,
        value=max(1, DEFAULT_ORDER_SIZE),
        step=1,
        help="Any whole-contract quantity is allowed. TP1/TP2/TP3 are allocated as closely as possible to 50%/30%/20%."
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

open_orders = get_result(
    open_orders_response
)

if not isinstance(open_orders, list):
    open_orders = []


# ============================================================
# FIND OUR PENDING ORDER
# ============================================================

pending_orders = []

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
# CANCEL PENDING ORDER ON DIRECTION CHANGE
# ============================================================

if pending_orders:

    for order in pending_orders:

        order_id = order.get("id")

        order_side = str(
            order.get(
                "side",
                ""
            )
        ).lower()


        should_cancel = False


        # ----------------------------------------------------
        # BUY PENDING + CURRENT SELL
        # ----------------------------------------------------

        if (
            order_side == "buy"
            and current_trend == 1
        ):

            should_cancel = True


        # ----------------------------------------------------
        # SELL PENDING + CURRENT BUY
        # ----------------------------------------------------

        elif (
            order_side == "sell"
            and current_trend == -1
        ):

            should_cancel = True


        # ----------------------------------------------------
        # CANCEL
        # ----------------------------------------------------

        if (
            should_cancel
            and remote_enabled
            and order_id is not None
        ):

            cancel_result = api.cancel_order(
                order_id
            )


            if cancel_result.get("success"):

                st.warning(
                    f"🔄 Pending {order_side.upper()} "
                    f"order CANCELLED — "
                    f"SuperTrend direction changed."
                )

                st.session_state[
                    "pending_order_id"
                ] = None
                st.session_state["entry_order_id"] = None
                st.session_state["entry_order_side"] = ""
                st.session_state["entry_order_size"] = 0


            else:

                st.error(
                    "Pending order cancel failed: "
                    + str(
                        cancel_result.get(
                            "error",
                            "Unknown error"
                        )
                    )
                )


# ============================================================
# ENTRY FILL -> PLACE T1/T2/T3 REDUCE-ONLY EXIT ORDERS
# ============================================================
# IMPORTANT:
# - The three targets are NOT sent when the entry LIMIT is merely submitted.
# - They are sent only after Delta reports the entry order as fully FILLED.
# - Target prices use the actual average fill price returned by Delta.
# - T1/T2/T3 are separate reduce-only LIMIT orders.
# ============================================================

def _clear_entry_target_state():
    st.session_state["pending_order_id"] = None
    st.session_state["pending_order_side"] = ""
    st.session_state["pending_order_time"] = 0
    st.session_state["entry_order_id"] = None
    st.session_state["entry_order_side"] = ""
    st.session_state["entry_order_size"] = 0
    st.session_state["entry_fill_price"] = None
    st.session_state["target_order_ids"] = []
    st.session_state["targets_placed_for_entry"] = None


def _cancel_remaining_target_orders(reason=""):
    target_ids = list(st.session_state.get("target_order_ids", []))
    cancelled = 0
    failed = 0

    for target_id in target_ids:
        if not target_id:
            continue
        try:
            cancel_result = api.cancel_order(target_id)
            if cancel_result.get("success"):
                cancelled += 1
            else:
                # It may already be filled/closed; do not treat that as a
                # trading failure during a reversal.
                failed += 1
        except Exception:
            failed += 1

    st.session_state["target_order_ids"] = []

    if cancelled:
        st.warning(
            f"🔄 {cancelled} remaining TARGET order(s) cancelled"
            + (f" — {reason}" if reason else "")
        )
    if failed and not cancelled:
        st.info(
            "Remaining target orders were already filled/closed or could not "
            "be cancelled; exchange state should be checked."
        )


# A NEW confirmed opposite SuperTrend signal cancels every still-open target.
_active_entry_side = str(
    st.session_state.get("entry_order_side", "")
).lower()
_new_signal = str(current_signal or "").upper()

if (
    _active_entry_side in ("buy", "sell")
    and _new_signal in ("BUY", "SELL")
    and (
        (_active_entry_side == "buy" and _new_signal == "SELL")
        or
        (_active_entry_side == "sell" and _new_signal == "BUY")
    )
):
    _cancel_remaining_target_orders(
        f"opposite SuperTrend {_new_signal}"
    )
    # Prevent the old entry from recreating its targets on the next rerun.
    _clear_entry_target_state()


# If an entry order exists, ask Delta for its authoritative state.
_entry_id = st.session_state.get("entry_order_id")

if _entry_id and remote_enabled:
    try:
        _entry_status_response = api.get_order(_entry_id)
        _entry_status = get_result(_entry_status_response)

        if isinstance(_entry_status, dict):
            _entry_state = str(
                _entry_status.get("state", "")
            ).lower()

            if _entry_state == "closed":
                _entry_unfilled = number(
                    _entry_status.get("unfilled_size"),
                    0
                )
                _entry_size = int(
                    number(
                        _entry_status.get(
                            "size",
                            st.session_state.get("entry_order_size", 0)
                        ),
                        0
                    )
                )
                _avg_fill = number(
                    _entry_status.get("average_fill_price"),
                    0
                )

                if (
                    _entry_unfilled <= 0
                    and _entry_size > 0
                    and _avg_fill > 0
                    and st.session_state.get("targets_placed_for_entry") != _entry_id
                ):
                    _entry_side = str(
                        st.session_state.get(
                            "entry_order_side",
                            _entry_status.get("side", "")
                        )
                    ).lower()

                    if _entry_side in ("buy", "sell"):
                        # TP distribution: 50% / 30% / 20%.
                        # Minimum entry size is 10 so all three integer quantities remain positive.
                        # Split the filled quantity as closely as possible to
                        # TP1=50%, TP2=30%, TP3=20%, while preserving the exact
                        # total quantity and using whole contracts. For 1-2
                        # contracts it is mathematically impossible to give all
                        # three targets a positive quantity, so the closest
                        # practical distribution is used.
                        if _entry_size <= 0:
                            raise ValueError("Filled entry quantity must be positive")

                        if _entry_size == 1:
                            _q1, _q2, _q3 = 1, 0, 0
                        elif _entry_size == 2:
                            _q1, _q2, _q3 = 1, 1, 0
                        else:
                            _ideal = (_entry_size * 0.50, _entry_size * 0.30, _entry_size * 0.20)
                            _best = None
                            _best_key = None
                            for _a in range(1, _entry_size - 1):
                                for _b in range(1, _entry_size - _a):
                                    _c = _entry_size - _a - _b
                                    if _c < 1 or not (_a >= _b >= _c):
                                        continue
                                    _err = (
                                        (_a - _ideal[0]) ** 2
                                        + (_b - _ideal[1]) ** 2
                                        + (_c - _ideal[2]) ** 2
                                    )
                                    # On an exact error tie, prefer more quantity
                                    # at TP1, then TP2.
                                    _key = (_err, -_a, -_b)
                                    if _best_key is None or _key < _best_key:
                                        _best_key = _key
                                        _best = (_a, _b, _c)
                            _q1, _q2, _q3 = _best

                        if _entry_side == "buy":
                            _actual_t1 = _avg_fill + float(t1_points)
                            _actual_t2 = _avg_fill + float(t2_points)
                            _actual_t3 = _avg_fill + float(t3_points)
                            _exit_side = "sell"
                        else:
                            _actual_t1 = _avg_fill - float(t1_points)
                            _actual_t2 = _avg_fill - float(t2_points)
                            _actual_t3 = _avg_fill - float(t3_points)
                            _exit_side = "buy"

                        _target_specs = [
                            ("T1", _q1, _actual_t1),
                            ("T2", _q2, _actual_t2),
                            ("T3", _q3, _actual_t3),
                        ]

                        _new_target_ids = []
                        _target_error = None

                        for _label, _qty, _price in _target_specs:
                            if int(_qty) <= 0:
                                _target_error = (
                                    f"{_label} quantity became 0; "
                                    "entry size must be at least 10."
                                )
                                break

                            _client_id = (
                                f"SR_{_label}_{_entry_id}"
                            )

                            _target_result = api.place_limit_order(
                                side=_exit_side,
                                size=int(_qty),
                                limit_price=_price,
                                reduce_only=True,
                                client_order_id=_client_id
                            )

                            if _target_result.get("success"):
                                _target_data = _target_result.get(
                                    "result",
                                    {}
                                )
                                _target_id = (
                                    _target_data.get("id")
                                    if isinstance(
                                        _target_data,
                                        dict
                                    )
                                    else None
                                )
                                if _target_id:
                                    _new_target_ids.append(_target_id)
                                else:
                                    _target_error = (
                                        f"{_label} order accepted but "
                                        "Delta did not return an order ID."
                                    )
                                    break
                            else:
                                _target_error = (
                                    f"{_label} target failed: "
                                    + str(
                                        _target_result.get(
                                            "error",
                                            "Unknown error"
                                        )
                                    )
                                )
                                break

                        if _target_error:
                            # Do not leave a partially protected position.
                            for _tid in _new_target_ids:
                                try:
                                    api.cancel_order(_tid)
                                except Exception:
                                    pass
                            st.error(
                                "❌ TARGET PLACEMENT FAILED — "
                                + _target_error
                                + " | Existing target orders from this entry "
                                  "were cancelled."
                            )
                        else:
                            st.session_state["target_order_ids"] = _new_target_ids
                            st.session_state["targets_placed_for_entry"] = _entry_id
                            st.session_state["entry_fill_price"] = _avg_fill

                            st.success(
                                "🎯 ENTRY FILLED — T1/T2/T3 REDUCE-ONLY "
                                "LIMIT ORDERS SENT"
                            )
                            st.write(
                                f"Actual Fill: **{show_price(_avg_fill)}** | "
                                f"T1: **{show_price(_actual_t1)} ({_q1})** | "
                                f"T2: **{show_price(_actual_t2)} ({_q2})** | "
                                f"T3: **{show_price(_actual_t3)} ({_q3})**"
                            )

            elif _entry_state in ("cancelled", "rejected"):
                st.warning(
                    f"Entry order {_entry_id} is {_entry_state.upper()}."
                )
                _clear_entry_target_state()

    except Exception as _entry_monitor_error:
        st.error(
            "Entry fill status check failed: "
            + str(_entry_monitor_error)
        )

# ============================================================
# SHOW PENDING ORDERS
# ============================================================

if pending_orders:

    pending_rows = []

    for order in pending_orders:

        pending_rows.append({

            "Order ID":
                order.get("id", "-"),

            "Side":
                str(
                    order.get(
                        "side",
                        ""
                    )
                ).upper(),

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

            "Status":
                order.get(
                    "state",
                    "-"
                )
        })


    st.dataframe(
        pd.DataFrame(
            pending_rows
        ),
        use_container_width=True,
        hide_index=True
    )

else:

    st.info(
        "No pending LIMIT order."
    )


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
        # PREVENT DUPLICATE ORDER
        # ----------------------------------------------------

        already_processed = (
            st.session_state[
                "last_order_signal"
            ]
            == current_signal_time
        )


        if already_processed:

            st.success(
                f"Signal already processed: "
                f"{signal_direction}"
            )

        else:

            order_side = (
                "buy"
                if signal_direction == "BUY"
                else "sell"
            )


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
            # BINA BUTTON KE DIRECT AUTOMATIC ORDER EXECUTION
            # ====================================================

            result = api.place_limit_order(
                side=order_side,
                size=int(order_size),
                limit_price=limit_entry_price
            )


            if result.get("success"):

                result_data = result.get(
                    "result",
                    {}
                )


                new_order_id = (
                    result_data.get("id")
                    if isinstance(
                        result_data,
                        dict
                    )
                    else None
                )


                st.session_state[
                    "pending_order_id"
                ] = new_order_id

                # Monitor this exact entry order until Delta reports a full fill.
                # T1/T2/T3 are created only after that confirmation.
                st.session_state["entry_order_id"] = new_order_id
                st.session_state["entry_order_side"] = order_side
                st.session_state["entry_order_size"] = int(order_size)
                st.session_state["entry_fill_price"] = None
                st.session_state["target_order_ids"] = []
                st.session_state["targets_placed_for_entry"] = None

                st.session_state[
                    "pending_order_side"
                ] = order_side


                st.session_state[
                    "pending_order_time"
                ] = time.time()


                st.session_state[
                    "last_order_signal"
                ] = current_signal_time


                st.success(
                    f"✅ REAL {signal_direction} "
                    f"LIMIT ORDER SENT AUTOMATICALLY"
                )


                st.write(
                    f"Order ID: "
                    f"**{new_order_id}**"
                )


            else:

                st.error(
                    "❌ REAL ORDER FAILED: "
                    + str(
                        result.get(
                            "error",
                            "Unknown error"
                        )
                    )
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
        style="height:100vh;width:100%;">

        <div
            class="tradingview-widget-container__widget"
            style="height:100%;width:100%;">
        </div>

        <script
            type="text/javascript"
            src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
            async>

        {
            "autosize": true,
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
# ============================================================
# LINE-BY-LINE DIAGNOSTIC PANEL — ADDED AT THE VERY BOTTOM
# ============================================================
st.divider()
st.subheader("🔎 LINE-BY-LINE SIGNATURE / API DIAGNOSTIC")

if st.session_state.get("line_diagnostic"):
    rows = []
    for item in st.session_state["line_diagnostic"]:
        status = item["status"]
        icon = "✅" if status == "PASSED" else ("❌" if status == "FAILED" else "⏳")
        rows.append({"LINE": item["line"], "STATUS": f"{icon} {status}", "STEP": item["step"], "DETAIL": item["detail"]})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    failed = [x for x in st.session_state["line_diagnostic"] if x["status"] == "FAILED"]
    if failed:
        last_failed = failed[-1]
        st.error(f"🚨 FAILURE LOCATION: LINE {last_failed['line']} — {last_failed['step']} | {last_failed['detail']}")
    else:
        st.success("✅ Diagnostic में अभी तक कोई FAILED step नहीं मिला।")
else:
    st.info("⏳ Diagnostic अभी run नहीं हुआ।")

# ============================================================
# AUTHENTICATION CONSISTENCY PANEL — ADDED AT THE VERY BOTTOM
# ============================================================
st.subheader("🔐 ACTUAL AUTHENTICATION CHECK")
_auth_items = [
    x for x in st.session_state.get("line_diagnostic", [])
    if x.get("step") in ("ACTUAL AUTH CHECK", "ACTUAL REQUEST VALUES")
]
if _auth_items:
    st.dataframe(
        pd.DataFrame([
            {
                "LINE": x.get("line"),
                "STATUS": x.get("status"),
                "CHECK": x.get("step"),
                "DETAIL": x.get("detail")
            }
            for x in _auth_items
        ]),
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("⏳ Actual authentication check अभी run नहीं हुआ।")

# ============================================================
# EXACT SIGNATURE COMPARISON PANEL — ADDED AT THE VERY BOTTOM
# ============================================================
st.subheader("🔬 EXACT SIGNATURE COMPARISON")

local_sig_data = str(st.session_state.get("last_signature_message", ""))
delta_sig_data = ""

# Read the most recent Delta error from the diagnostic entries.
for _item in reversed(st.session_state.get("line_diagnostic", [])):
    if _item.get("step") == "DELTA RESPONSE":
        _detail = str(_item.get("detail", ""))
        try:
            _response_json_text = _detail.split(" | ", 1)[1]
            _response_obj = json.loads(_response_json_text)
            delta_sig_data = str(
                _response_obj.get("error", {}).get("context", {}).get("signature_data", "")
            )
        except Exception:
            pass
        if delta_sig_data:
            break

if local_sig_data:
    st.text_area(
        "OUR SIGNATURE DATA (EXACT)",
        local_sig_data,
        height=120,
        key="diag_local_signature_data"
    )
else:
    st.info("⏳ Local signature_data अभी उपलब्ध नहीं है।")

if delta_sig_data:
    st.text_area(
        "DELTA SIGNATURE DATA (EXACT)",
        delta_sig_data,
        height=120,
        key="diag_delta_signature_data"
    )

    if local_sig_data == delta_sig_data:
        st.success("✅ EXACT MATCH — Local और Delta का signature_data बिल्कुल समान है।")
    else:
        first_diff = None
        for _idx in range(max(len(local_sig_data), len(delta_sig_data))):
            _a = local_sig_data[_idx] if _idx < len(local_sig_data) else "<END>"
            _b = delta_sig_data[_idx] if _idx < len(delta_sig_data) else "<END>"
            if _a != _b:
                first_diff = _idx
                break
        if first_diff is None:
            first_diff = min(len(local_sig_data), len(delta_sig_data))
        st.error(f"❌ EXACT MISMATCH — पहला अलग character: {first_diff}")
else:
    st.warning("⚠️ Delta ने इस response में signature_data नहीं दिया, इसलिए exact comparison अभी नहीं हो सका।")

# ============================================================
# ORIGINAL SOURCE-LINE MAP — ADDED ONLY
# IMPORTANT: These are the ORIGINAL file's online/source line numbers.
# Diagnostic code lines are NOT shown here.
# ============================================================
st.subheader("📍 ORIGINAL CODE LINE MAP — SIGNATURE / API")
st.caption(
    "यहाँ LINE नंबर original trading code के हैं। "
    "हर संबंधित original line के आगे उसी part का ✅/❌/⏳ निशान है।"
)

# These ranges are based on the original source file before diagnostic additions.
_original_ranges = [
    (636, 647, "DeltaAPI initialization / API credentials / session"),
    (656, 677, "HMAC signature — make_signature()"),
    (684, 714, "request() — params/body/query + headers"),
    (717, 746, "PRIVATE authentication — timestamp/signature/headers"),
    (751, 780, "HTTP request + response JSON"),
    (820, 830, "open_orders() — private GET /v2/orders"),
    (833, 842, "position() — private GET /v2/positions"),
    (849, 879, "place_limit_order() — private POST /v2/orders"),
    (886, 892, "cancel_order() — private DELETE /v2/orders"),
]

# Resolve the latest diagnostic status for a named diagnostic step.
# This helper is intentionally placed before _original_status so the line-map
# section cannot raise NameError during Streamlit startup.
def _latest_status(*_steps):
    _entries = st.session_state.get("line_diagnostic", [])
    for _entry in reversed(_entries):
        if str(_entry.get("step", "")) in _steps:
            return str(_entry.get("status", "WAITING"))
    return "WAITING"

# Status for each original source range.
_original_status = {
    "DeltaAPI initialization / API credentials / session": _latest_status("ACTUAL AUTH CHECK"),
    "HMAC signature — make_signature()": _latest_status("SIGNATURE MESSAGE"),
    "request() — params/body/query + headers": _latest_status("SIGNATURE MESSAGE", "HEADERS / SIGNATURE"),
    "PRIVATE authentication — timestamp/signature/headers": _latest_status("TIMESTAMP", "HEADERS / SIGNATURE", "ACTUAL AUTH CHECK"),
    "HTTP request + response JSON": _latest_status("DELTA API REQUEST", "ACTUAL REQUEST VALUES", "DELTA RESPONSE", "RESPONSE JSON"),
    "open_orders() — private GET /v2/orders": _latest_status("DELTA RESPONSE", "EXACT SIGNATURE DATA COMPARE"),
    "position() — private GET /v2/positions": _latest_status("DELTA RESPONSE", "EXACT SIGNATURE DATA COMPARE"),
    "place_limit_order() — private POST /v2/orders": _latest_status("DELTA RESPONSE", "EXACT SIGNATURE DATA COMPARE"),
    "cancel_order() — private DELETE /v2/orders": _latest_status("DELTA RESPONSE"),
}

def _mark_for_status(_status):
    return "❌" if _status == "FAILED" else ("✅" if _status == "PASSED" else "⏳")

_original_map_rows = []
for _start, _end, _part in _original_ranges:
    _st = _original_status.get(_part, "WAITING")
    _original_map_rows.append({
        "MARK": _mark_for_status(_st),
        "ORIGINAL LINE RANGE": f"{_start}-{_end}",
        "PART": _part,
        "STATUS": _st,
    })

st.dataframe(
    pd.DataFrame(_original_map_rows),
    use_container_width=True,
    hide_index=True
)

# Exact original source lines are embedded from the original file so that
# added diagnostic code can never change the displayed original line numbers.
_original_source_snapshot = {
    636: 'class DeltaAPI:',
    637: '',
    638: '    def __init__(self, api_key=None, api_secret=None):',
    639: '        self.api_key = str(api_key or "").strip()',
    640: '        self.api_secret = str(api_secret or "").strip()',
    641: '',
    642: '        self.session = requests.Session()',
    643: '',
    644: '        self.session.headers.update({',
    645: '            "User-Agent": "Sanjay-Rana-Real-Trading-Bot",',
    646: '            "Accept": "application/json"',
    647: '        })',
    656: '    def make_signature(',
    657: '        self,',
    658: '        method,',
    659: '        timestamp,',
    660: '        path,',
    661: '        query_string="",',
    662: '        body=""',
    663: '    ):',
    664: '',
    665: '        message = (',
    666: '            method.upper()',
    667: '            + timestamp',
    668: '            + path',
    669: '            + query_string',
    670: '            + body',
    671: '        )',
    672: '',
    673: '        return hmac.new(',
    674: '            self.api_secret.encode("utf-8"),',
    675: '            message.encode("utf-8"),',
    676: '            hashlib.sha256',
    677: '        ).hexdigest()',
    684: '    def request(',
    685: '        self,',
    686: '        method,',
    687: '        path,',
    688: '        params=None,',
    689: '        body=None,',
    690: '        private=False',
    691: '    ):',
    692: '',
    693: '        params = params or {}',
    694: '',
    695: '        body = body or {}',
    696: '',
    697: '        payload = ""',
    698: '',
    699: '        if body:',
    700: '            payload = json.dumps(',
    701: '                body,',
    702: '                separators=(",", ":")',
    703: '            )',
    704: '',
    705: '        query_string = ""',
    706: '',
    707: '        if params:',
    708: '            query_string = "?" + urlencode(params, doseq=True)',
    709: '',
    710: '',
    711: '        headers = {',
    712: '            "Accept": "application/json",',
    713: '            "User-Agent": "Sanjay-Rana-Real-Trading-Bot"',
    714: '        }',
    717: '        if private:',
    718: '',
    719: '            if not self.api_key or not self.api_secret:',
    720: '',
    721: '                return {',
    722: '                    "success": False,',
    723: '                    "error": "API key/secret missing"',
    724: '                }',
    725: '',
    726: '',
    727: '            timestamp = str(',
    728: '                int(time.time())',
    729: '            )',
    730: '',
    731: '',
    732: '            signature = self.make_signature(',
    733: '                method,',
    734: '                timestamp,',
    735: '                path,',
    736: '                query_string,',
    737: '                payload',
    738: '            )',
    739: '',
    740: '',
    741: '            headers.update({',
    742: '                "api-key": self.api_key,',
    743: '                "timestamp": timestamp,',
    744: '                "signature": signature,',
    745: '                "Content-Type": "application/json"',
    746: '            })',
    751: '            response = self.session.request(',
    752: '                method.upper(),',
    753: '                BASE_URL + path,',
    754: '                params=params,',
    755: '                data=payload if payload else None,',
    756: '                headers=headers,',
    757: '                timeout=(3, 27)',
    758: '            )',
    759: '',
    760: '',
    761: '            try:',
    762: '                data = response.json()',
    763: '',
    764: '            except Exception:',
    765: '',
    766: '                return {',
    767: '                    "success": False,',
    768: '                    "error": response.text',
    769: '                }',
    770: '',
    771: '',
    772: '            return data',
    773: '',
    774: '',
    775: '        except Exception as e:',
    776: '',
    777: '            return {',
    778: '                "success": False,',
    779: '                "error": str(e)',
    780: '            }',
    820: '    def open_orders(self):',
    821: '',
    822: '        return self.request(',
    823: '            "GET",',
    824: '            "/v2/orders",',
    825: '            params={',
    826: '                "product_id": PRODUCT_ID,',
    827: '                "state": "open"',
    828: '            },',
    829: '            private=True',
    830: '        )',
    833: '    def position(self):',
    834: '',
    835: '        return self.request(',
    836: '            "GET",',
    837: '            "/v2/positions",',
    838: '            params={',
    839: '                "product_id": PRODUCT_ID',
    840: '            },',
    841: '            private=True',
    842: '        )',
    849: '    def place_limit_order(',
    850: '        self,',
    851: '        side,',
    852: '        size,',
    853: '        limit_price',
    854: '    ):',
    855: '',
    856: '        body = {',
    857: '',
    858: '            "product_id": PRODUCT_ID,',
    859: '',
    860: '            "product_symbol": SYMBOL,',
    861: '',
    862: '            "limit_price": str(',
    863: '                limit_price',
    864: '            ),',
    865: '',
    866: '            "size": int(size),',
    867: '',
    868: '            "side": side,',
    869: '',
    870: '            "order_type": "limit_order"',
    871: '        }',
    872: '',
    873: '',
    874: '        return self.request(',
    875: '            "POST",',
    876: '            "/v2/orders",',
    877: '            body=body,',
    878: '            private=True',
    879: '        )',
    886: '    def cancel_order(self, order_id):',
    887: '',
    888: '        return self.request(',
    889: '            "DELETE",',
    890: '            f"/v2/orders/{order_id}",',
    891: '            private=True',
    892: '        )',
}

st.subheader("🧾 ORIGINAL SOURCE LINES WITH MARKS")
_original_failed_parts = []
for _start, _end, _part in _original_ranges:
    _st = _original_status.get(_part, "WAITING")
    _icon = _mark_for_status(_st)
    if _st == "FAILED":
        _original_failed_parts.append(f"LINE {_start}-{_end} — {_part}")

_marked_original_lines = []
for _start, _end, _part in _original_ranges:
    _st = _original_status.get(_part, "WAITING")
    _icon = _mark_for_status(_st)
    for _n in range(_start, _end + 1):
        _text = _original_source_snapshot.get(_n, "")
        _marked_original_lines.append(
            f"{_icon} LINE {_n:04d} | {_text}"
        )

st.code("\n".join(_marked_original_lines), language="python")

if _original_failed_parts:
    st.error(
        "🚨 ORIGINAL CODE FAILURE RANGE:\n" +
        "\n".join(_original_failed_parts)
    )
else:
    st.success("✅ अभी किसी original code range को FAILED नहीं चिन्हित किया गया है।")

# ============================================================
# MOBILE / APP-READABLE DISPLAY — ADDED ONLY
# Keeps the dashboard readable on a phone/app WebView.
# Does not change trading/API logic.
# ============================================================
st.markdown("""
<style>
/* Large, readable controls and tables on phone-sized screens. */
html, body, [class*="stApp"] {
    font-size: 18px !important;
}

@media (max-width: 900px) {
    .block-container {
        padding-left: 0.65rem !important;
        padding-right: 0.65rem !important;
        padding-top: 0.65rem !important;
        padding-bottom: 2rem !important;
        max-width: 100% !important;
    }

    h1 { font-size: 1.65rem !important; }
    h2 { font-size: 1.40rem !important; }
    h3 { font-size: 1.20rem !important; }

    button, input, textarea, select,
    [data-testid="stSelectbox"],
    [data-testid="stNumberInput"],
    [data-testid="stTextInput"] {
        font-size: 17px !important;
    }

    [data-testid="stDataFrame"] {
        font-size: 16px !important;
    }

    .stRadio label, .stCheckbox label,
    .stButton button, .stMarkdown, .stCaption {
        font-size: 17px !important;
    }
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# KEY + SECRET PAIRING / ENVIRONMENT VERIFICATION — ADDED ONLY
# This block does NOT change the original trading/API code above.
# It uses Delta's documented WebSocket key-auth handshake because the
# response distinguishes invalid signature, missing key and IP whitelist.
# ============================================================
st.divider()
st.subheader("🔐 API KEY + SECRET PAIRING / ENVIRONMENT CHECK")
st.caption(
    "यह check original trading request को नहीं बदलता। यह अलग से Delta के "
    "documented key-auth handshake से API key + secret + environment की जांच करता है।"
)


def _verify_delta_key_secret_environment(_api_key, _api_secret, _label):
    _result = {
        "label": _label,
        "environment": "",
        "status": "",
        "detail": "",
        "key_fingerprint": "",
        "secret_fingerprint": "",
    }

    _key = str(_api_key or "").strip()
    _secret = str(_api_secret or "").strip()

    _result["key_fingerprint"] = (
        f"len={len(_key)} | SHA256={hashlib.sha256(_key.encode('utf-8')).hexdigest()[:16]}"
        if _key else "MISSING"
    )
    _result["secret_fingerprint"] = (
        f"len={len(_secret)} | SHA256={hashlib.sha256(_secret.encode('utf-8')).hexdigest()[:16]}"
        if _secret else "MISSING"
    )

    if not _key or not _secret:
        _result["environment"] = BASE_URL
        _result["status"] = "FAILED"
        _result["detail"] = "API key या API secret missing है।"
        return _result

    _base = str(BASE_URL).rstrip("/")
    if "api.india.delta.exchange" in _base:
        _result["environment"] = "PRODUCTION — api.india.delta.exchange"
    elif "testnet" in _base or "cdn-ind.testnet.deltaex.org" in _base:
        _result["environment"] = "DEMO / TESTNET — cdn-ind.testnet.deltaex.org"
    else:
        _result["environment"] = f"UNKNOWN BASE URL — {_base}"

    try:
        import websocket as _websocket

        if _base == "https://api.india.delta.exchange":
            _ws_url = "wss://socket.india.delta.exchange"
        elif "cdn-ind.testnet.deltaex.org" in _base or "testnet" in _base:
            _ws_url = "wss://socket-ind.testnet.deltaex.org"
        else:
            _result["status"] = "FAILED"
            _result["detail"] = "Base URL documented India production/testnet endpoint से match नहीं करता।"
            return _result

        _timestamp = str(int(time.time()))
        _signature_data = "GET" + _timestamp + "/live"
        _signature = hmac.new(
            _secret.encode("utf-8"),
            _signature_data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        _ws = _websocket.create_connection(_ws_url, timeout=6)
        try:
            _ws.send(json.dumps({
                "type": "key-auth",
                "payload": {
                    "api-key": _key,
                    "signature": _signature,
                    "timestamp": _timestamp,
                },
            }))
            _raw = _ws.recv()
        finally:
            try:
                _ws.close()
            except Exception:
                pass

        _obj = json.loads(_raw) if isinstance(_raw, str) else {}
        _success = bool(_obj.get("success"))
        _status = str(_obj.get("status", ""))
        _message = str(_obj.get("message", ""))

        if _success:
            _result["status"] = "PASSED"
            _result["detail"] = "Delta key-auth ने API key + secret pair स्वीकार किया।"
        elif _status == "api_key_not_found":
            _result["status"] = "FAILED"
            _result["detail"] = "API key इस environment में नहीं मिली — wrong environment/key या key deleted हो सकती है।"
        elif _status == "invalid_signature":
            _result["status"] = "FAILED"
            _result["detail"] = "API key मिली, लेकिन secret से बनी signature स्वीकार नहीं हुई — key/secret pairing verify करें।"
        elif _status == "ip_not_whitelisted":
            _result["status"] = "FAILED"
            _result["detail"] = "Key/secret authentication तक पहुँची, लेकिन current server IP whitelist में नहीं है।"
        elif _status == "request_expired":
            _result["status"] = "FAILED"
            _result["detail"] = "Timestamp 5-second window से बाहर पहुँचा।"
        else:
            _result["status"] = "FAILED"
            _result["detail"] = f"Delta key-auth response: status={_status or 'unknown'} | message={_message or 'none'}"

    except Exception as _verify_error:
        _result["status"] = "FAILED"
        _result["detail"] = f"Verification transport/error: {type(_verify_error).__name__}: {_verify_error}"

    return _result


# Run once per credential fingerprint in this Streamlit session to avoid
# repeatedly opening WebSocket authentication connections on every rerun.
_pairing_results = []
_pairing_targets = [
    ("OWNER", OWNER_API_KEY, OWNER_API_SECRET),
]

for _pair_label, _pair_key, _pair_secret in _pairing_targets:
    _pair_cache_id = hashlib.sha256(
        (str(_pair_key or "") + "|" + str(_pair_secret or "") + "|" + str(BASE_URL)).encode("utf-8")
    ).hexdigest()[:16]
    _pair_cache_key = f"pairing_environment_check_{_pair_label}_{_pair_cache_id}"
    if _pair_cache_key not in st.session_state:
        st.session_state[_pair_cache_key] = _verify_delta_key_secret_environment(
            _pair_key, _pair_secret, _pair_label
        )
    _pairing_results.append(st.session_state[_pair_cache_key])

_pairing_rows = []
for _pr in _pairing_results:
    _pairing_rows.append({
        "API": _pr["label"],
        "ENVIRONMENT": _pr["environment"],
        "STATUS": ("✅ PASSED" if _pr["status"] == "PASSED" else "❌ FAILED"),
        "DETAIL": _pr["detail"],
        "KEY FINGERPRINT": _pr["key_fingerprint"],
        "SECRET FINGERPRINT": _pr["secret_fingerprint"],
    })

st.dataframe(pd.DataFrame(_pairing_rows), use_container_width=True, hide_index=True)

for _pr in _pairing_results:
    if _pr["status"] == "PASSED":
        st.success(
            f"✅ {_pr['label']}: Delta ने इसी environment में API key + secret pair स्वीकार कर लिया। "
            "इसका मतलब key/secret pairing और environment authentication पास है।"
        )
    else:
        st.error(
            f"❌ {_pr['label']}: {_pr['detail']}"
        )

st.caption(
    "नोट: Secret कभी display नहीं किया गया है; केवल length और SHA256 fingerprint दिखाया गया है।"
)

# ============================================================
# FIVE SEPARATE CREDENTIAL / ENVIRONMENT CHECKS — ADDED ONLY
# ============================================================
st.divider()
st.subheader("🔎 5 अलग-अलग API CHECK")
st.caption("हर check का परिणाम अलग दिखेगा; इससे कोई गलत संयुक्त निशान नहीं लगेगा।")

for _pr in _pairing_results:
    _k_ok = bool(str(OWNER_API_KEY or "").strip())
    _s_ok = bool(str(OWNER_API_SECRET or "").strip())
    _pair_detail = str(_pr.get("detail", ""))
    _pair_status = str(_pr.get("status", ""))
    _env_ok = str(_pr.get("environment", "")).startswith("PRODUCTION — api.india.delta.exchange")
    _delta_ok = _pair_status == "PASSED"
    _pair_ok = _delta_ok

    _five_checks = [
        ("API Key मिली है?", _k_ok, "Streamlit secret से API key मिली है।" if _k_ok else "API key खाली/missing है।"),
        ("API Secret मिला है?", _s_ok, "Streamlit secret से API secret मिला है।" if _s_ok else "API secret खाली/missing है।"),
        ("API Key और Secret की जोड़ी सही है?", _pair_ok,
         "Delta key-auth ने इसी pair को स्वीकार किया।" if _pair_ok else
         "Delta ने इस pair को स्वीकार नहीं किया। नीचे मूल Delta response देखें।"),
        ("यह Production API है?", _env_ok,
         "Base URL India Production है।" if _env_ok else
         f"Production नहीं है: {_pr.get('environment', BASE_URL)}"),
        ("Delta ने इस Key को स्वीकार किया?", _delta_ok,
         "Delta ने key-auth स्वीकार किया।" if _delta_ok else
         f"Delta ने स्वीकार नहीं किया: {_pair_detail}"),
    ]

    st.markdown(f"### 🔐 {_pr['label']}")
    for _question, _ok, _detail in _five_checks:
        if _ok:
            st.success(f"✅ {_question}  —  {_detail}")
        else:
            st.error(f"❌ {_question}  —  {_detail}")

    if all(_ok for _, _ok, _ in _five_checks):
        st.success("🟢 सभी CHECK PASSED — Key, Secret, pairing, Production environment और Delta authentication सही है।")
    else:
        st.warning("🟡 सभी CHECK PASSED नहीं हुए। जिस line पर ❌ है, वही अगली जांच का मुख्य बिंदु है।")


time.sleep(REFRESH_SECONDS)
st.rerun()


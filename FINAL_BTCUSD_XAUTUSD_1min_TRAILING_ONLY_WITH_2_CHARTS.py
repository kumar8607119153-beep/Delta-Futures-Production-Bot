
# ============================================================
# SANJAY RANA — DELTA REAL TRADING DASHBOARD
# BTCUSD + XAUTUSD | 1-MINUTE | SUPERTREND 10,3 | 1 LOT EACH
# ============================================================
#
# REAL TRADING:
#   BTCUSD  -> 1 contract / 1 lot
#   XAUTUSD -> 1 contract / 1 lot
#
# IMPORTANT:
#   Delta's exchange symbol for the gold contract shown by the user
#   is XAUTUSD (Tether Gold Token Perpetual). The UI may call it
#   XAUTUSDT for display, but real Delta API orders use XAUTUSD.
#
#   Product IDs are resolved automatically from Delta by symbol.
#   No BTC Product ID is reused for XAUTUSD.
#
#   Trading decision:
#     - 1-minute candles only
#     - only fully closed candles
#     - ATR 10
#     - Multiplier 3.0
#     - HL2
#     - BUY on Bearish -> Bullish flip
#     - SELL on Bullish -> Bearish flip
#
#   Each symbol is completely independent:
#     BTCUSD  -> its own candles, ST, signal, position and orders
#     XAUTUSD -> its own candles, ST, signal, position and orders
#
# ============================================================

import os
import time
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Sanjay Rana — BTC + XAUTUSD",
    page_icon="📈",
    layout="wide"
)


# ============================================================
# DELTA SETTINGS
# ============================================================

BASE_URL = os.getenv(
    "DELTA_BASE_URL",
    "https://api.india.delta.exchange"
).rstrip("/")

TIMEFRAME = "1m"
CANDLE_SECONDS = 60

ATR_PERIOD = 10
MULTIPLIER = 3.0

REFRESH_SECONDS = int(
    os.getenv("REFRESH_SECONDS", "5")
)

# One lot / one contract for EACH market.
BTC_LOTS = 1
XAUT_LOTS = 1

# Existing limit/target style is kept.
BUY_OFFSET = float(
    os.getenv("BUY_OFFSET", "-150")
)
SELL_OFFSET = float(
    os.getenv("SELL_OFFSET", "150")
)

# Market-specific target plan.
# Targets are based on the confirmed 1-minute ATR, so BTC and XAUT
# do not use the same fixed dollar distance.
#
# 1 lot is kept intact. Therefore only T1 is attached as the
# executable TP; T2/T3 are calculated/displayed as extended targets.
# Fixed TP disabled; ATR is used only for trailing.

# Fixed TP is OFF; trailing is independent. Trailing is NOT used as TP.
TRAIL_ATR_MULTIPLIERS = {
    "BTCUSD": 0.75,
    "XAUTUSD": 0.50,
}

# Real trading is intentionally active by default for this requested
# real-trading file. Set REMOTE_TRADING=false to stop new orders.
REMOTE_TRADING = (
    os.getenv("REMOTE_TRADING", "true").lower() == "true"
)


# ============================================================
# SYMBOLS
# ============================================================

MARKETS = {
    "BTCUSD": {
        "symbol": "BTCUSD",
        "display": "BTC",
        "lots": BTC_LOTS,
    },
    "XAUTUSD": {
        "symbol": "XAUTUSD",
        "display": "XAUTUSD",
        "lots": XAUT_LOTS,
    },
}


# ============================================================
# TIME
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))


def indian_time(timestamp):
    try:
        ts = float(timestamp)

        if ts > 10_000_000_000:
            ts /= 1000.0

        return datetime.fromtimestamp(
            ts,
            tz=timezone.utc
        ).astimezone(IST).strftime(
            "%Y-%m-%d %H:%M:%S IST"
        )

    except Exception:
        return "-"


def now_ist_text():
    return datetime.now(
        timezone.utc
    ).astimezone(IST).strftime(
        "%Y-%m-%d %H:%M:%S IST"
    )


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


def get_result(data):
    if not isinstance(data, dict):
        return None

    if not data.get("success"):
        return None

    return data.get("result")


# ============================================================
# PRODUCT RESOLUTION
# ============================================================

def resolve_product(symbol):
    response = requests.get(
        f"{BASE_URL}/v2/products/{symbol}",
        headers={
            "Accept": "application/json",
            "User-Agent": "Sanjay-Rana-Dual-Real-Trading"
        },
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        raise RuntimeError(
            f"Delta product lookup failed for {symbol}: {data}"
        )

    product = data.get("result")

    if not isinstance(product, dict):
        raise RuntimeError(
            f"Invalid Delta product response for {symbol}"
        )

    returned_symbol = str(
        product.get("symbol", "")
    ).upper()

    if returned_symbol != symbol.upper():
        raise RuntimeError(
            f"Symbol mismatch: requested {symbol}, "
            f"received {returned_symbol}"
        )

    product_id = product.get("id")

    if product_id is None:
        raise RuntimeError(
            f"Delta did not return Product ID for {symbol}"
        )

    return int(product_id), product


# ============================================================
# DELTA API
# ============================================================

class DeltaAPI:

    def __init__(
        self,
        api_key,
        api_secret,
        symbol,
        product_id
    ):
        self.api_key = str(
            api_key or ""
        ).strip()

        self.api_secret = str(
            api_secret or ""
        ).strip()

        self.symbol = symbol
        self.product_id = int(product_id)

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": "Sanjay-Rana-Dual-Real-Trading",
            "Accept": "application/json"
        })

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
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

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
            query_string = "?" + "&".join(
                f"{key}={value}"
                for key, value in params.items()
            )

        headers = {
            "Accept": "application/json",
            "User-Agent": "Sanjay-Rana-Dual-Real-Trading"
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

            signature = self.make_signature(
                method,
                timestamp,
                path,
                query_string,
                payload
            )

            headers.update({
                "api-key": self.api_key,
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
                return response.json()
            except Exception:
                return {
                    "success": False,
                    "error": response.text
                }

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc)
            }

    # ---------------- PUBLIC ----------------

    def candles(self):
        end = int(time.time())

        start = end - (
            500 * CANDLE_SECONDS
        )

        return self.request(
            "GET",
            "/v2/history/candles",
            params={
                "symbol": self.symbol,
                "resolution": TIMEFRAME,
                "start": start,
                "end": end
            }
        )

    def ticker(self):
        return self.request(
            "GET",
            f"/v2/tickers/{self.symbol}"
        )

    # ---------------- PRIVATE ----------------

    def open_orders(self):
        return self.request(
            "GET",
            "/v2/orders",
            params={
                "product_id": self.product_id,
                "state": "open"
            },
            private=True
        )

    def closed_orders(self):
        return self.request(
            "GET",
            "/v2/orders",
            params={
                "product_id": self.product_id,
                "state": "closed"
            },
            private=True
        )

    def position(self):
        return self.request(
            "GET",
            "/v2/positions",
            params={
                "product_id": self.product_id
            },
            private=True
        )

    def place_limit_order(
        self,
        side,
        size,
        limit_price,
        take_profit_price,
        client_order_id,
        trailing_amount=None
    ):
        body = {
            "product_id": self.product_id,
            "limit_price": str(limit_price),
            "size": int(size),
            "side": side,
            "order_type": "limit_order",
            "time_in_force": "gtc",
            "post_only": False,
            "reduce_only": False,
            "client_order_id": str(
                client_order_id
            )[:32],
            "bracket_take_profit_price": str(
                take_profit_price
            ),
            "bracket_take_profit_limit_price": str(
                take_profit_price
            ),
            "bracket_stop_trigger_method": (
                "last_traded_price"
            ),
        }

        # IMPORTANT: TP and trailing are separate controls.
        # TP uses bracket_take_profit_* above.
        # Trailing uses bracket_trail_amount only when explicitly enabled.
        if trailing_amount is not None and float(trailing_amount) > 0:
            trail = abs(float(trailing_amount))
            # Delta validation: BUY trailing amount must be negative.
            # SELL is the opposite direction.
            body["bracket_trail_amount"] = str(
                -trail if side.lower() == "buy" else trail
            )


        return self.request(
            "POST",
            "/v2/orders",
            body=body,
            private=True
        )

    def place_market_reduce_only(
        self,
        side,
        size,
        client_order_id
    ):
        body = {
            "product_id": self.product_id,
            "size": int(abs(size)),
            "side": side,
            "order_type": "market_order",
            "reduce_only": True,
            "client_order_id": str(
                client_order_id
            )[:32],
        }

        return self.request(
            "POST",
            "/v2/orders",
            body=body,
            private=True
        )

    def cancel_order(self, order_id):
        return self.request(
            "DELETE",
            f"/v2/orders/{order_id}",
            private=True
        )


# ============================================================
# CREDENTIALS
# ============================================================

try:
    OWNER_API_KEY = st.secrets.get(
        "OWNER_API_KEY",
        os.getenv("OWNER_API_KEY", "")
    )

    OWNER_API_SECRET = st.secrets.get(
        "OWNER_API_SECRET",
        os.getenv("OWNER_API_SECRET", "")
    )

except Exception:
    OWNER_API_KEY = os.getenv(
        "OWNER_API_KEY",
        ""
    )

    OWNER_API_SECRET = os.getenv(
        "OWNER_API_SECRET",
        ""
    )


# ============================================================
# RESOLVE BOTH PRODUCTS
# ============================================================

product_info = {}
product_errors = {}

for market_name, market in MARKETS.items():
    try:
        pid, product = resolve_product(
            market["symbol"]
        )

        product_info[market_name] = {
            "product_id": pid,
            "product": product,
        }

    except Exception as exc:
        product_errors[market_name] = str(exc)


# ============================================================
# PAGE HEADER
# ============================================================

st.title(
    "📈 SANJAY RANA — BTC + XAUTUSD REAL TRADING"
)

st.caption(
    "BTCUSD + XAUTUSD | 1 Minute | ATR 10 | "
    "Multiplier 3.0 | HL2 | Confirmed Candle Close | "
    "1 Lot Each"
)


if product_errors:
    for market_name, error in product_errors.items():
        st.error(
            f"❌ {market_name} PRODUCT CHECK FAILED: {error}"
        )

    st.warning(
        "जिस market का Product ID Delta से verify नहीं हुआ, "
        "उस market पर कोई order नहीं भेजा जाएगा."
    )


# ============================================================
# OWNER CONNECTION
# ============================================================

st.info(
    "⚡ LIVE TRADING MODE: "
    + ("ACTIVE" if REMOTE_TRADING else "PAUSED")
)

owner_client = None
owner_connected = False

if not OWNER_API_KEY or not OWNER_API_SECRET:
    st.error(
        "❌ OWNER_API_KEY / OWNER_API_SECRET missing."
    )
else:
    # Connection test against BTC if available; otherwise XAUTUSD.
    test_market = (
        "BTCUSD"
        if "BTCUSD" in product_info
        else "XAUTUSD"
    )

    if test_market in product_info:
        owner_client = DeltaAPI(
            OWNER_API_KEY,
            OWNER_API_SECRET,
            test_market,
            product_info[test_market]["product_id"]
        )

        owner_result = owner_client.position()

        if owner_result.get("success"):
            owner_connected = True
            st.success(
                "👑 OWNER API: CONNECTED & LIVE 🟢"
            )
        else:
            err = str(
                owner_result.get(
                    "error",
                    "Unknown error"
                )
            )

            if (
                "ip" in err.lower()
                or "whitelist" in err.lower()
            ):
                st.error(
                    "🌐 OWNER IP WHITELIST ERROR: "
                    + err
                )
            else:
                st.error(
                    "🔴 OWNER API NOT CONNECTED: "
                    + err
                )


# ============================================================
# DATA HELPERS
# ============================================================

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
                "volume": float(
                    candle.get("volume", 0)
                )
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
# SUPERTREND 10,3 — IDENTICAL ENGINE FOR BOTH MARKETS
# ============================================================

def calculate_supertrend(df):
    df = df.copy()

    if df.empty:
        return df

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

    df["ATR"] = float("nan")

    if len(df) >= ATR_PERIOD:
        df.loc[
            ATR_PERIOD - 1,
            "ATR"
        ] = df["TR"].iloc[
            :ATR_PERIOD
        ].mean()

        for i in range(
            ATR_PERIOD,
            len(df)
        ):
            df.loc[i, "ATR"] = (
                df.loc[i - 1, "ATR"]
                * (ATR_PERIOD - 1)
                + df.loc[i, "TR"]
            ) / ATR_PERIOD

    df["HL2"] = (
        df["high"] + df["low"]
    ) / 2.0

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

        hl2 = float(
            df.loc[i, "HL2"]
        )

        close = float(
            df.loc[i, "close"]
        )

        basic_upper = (
            hl2 + MULTIPLIER * float(atr)
        )

        basic_lower = (
            hl2 - MULTIPLIER * float(atr)
        )

        if (
            i == ATR_PERIOD - 1
            or prev_final_upper is None
        ):
            final_upper = basic_upper
            final_lower = basic_lower

        else:
            previous_close = float(
                df.loc[i - 1, "close"]
            )

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

        df.loc[
            i,
            "FINAL_UPPER"
        ] = final_upper

        df.loc[
            i,
            "FINAL_LOWER"
        ] = final_lower

        if (
            i == ATR_PERIOD - 1
            or prev_supertrend is None
        ):
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

        df.loc[
            i,
            "ST_DIRECTION"
        ] = direction

        df.loc[
            i,
            "SUPERTREND"
        ] = supertrend

        if (
            i > 0
            and prev_direction != direction
        ):
            if direction == -1:
                df.loc[i, "SIGNAL"] = "BUY"

            elif direction == 1:
                df.loc[i, "SIGNAL"] = "SELL"

        prev_final_upper = final_upper
        prev_final_lower = final_lower
        prev_supertrend = supertrend
        prev_direction = direction

    return df


# ============================================================
# POSITION HELPERS
# ============================================================

def position_from_response(response):
    data = get_result(response)

    if isinstance(data, list):
        return (
            data[0]
            if data
            else {}
        )

    if isinstance(data, dict):
        return data

    return {}


def position_size(response):
    position = position_from_response(
        response
    )

    return number(
        position.get("size"),
        0
    )


# ============================================================
# MARKET ENGINE
# ============================================================

def process_market(
    market_name,
    market,
    product_data,
    api
):
    symbol = market["symbol"]
    display = market["display"]
    lot_size = int(market["lots"])
    product = product_data["product"]

    st.divider()

    st.header(
        f"📊 {display} — 1 MINUTE SUPERTREND 10,3"
    )

    pid = product_data["product_id"]

    st.caption(
        f"Delta Symbol: {symbol} | "
        f"Product ID: {pid} | "
        f"1 Lot / 1 Contract"
    )

    
def calculate_trailing_amount(symbol, atr_value):
    """Calculate exchange trailing distance independently for each contract."""
    mult = TRAIL_ATR_MULTIPLIERS.get(symbol, 0.5)
    try:
        amount = abs(float(atr_value)) * float(mult)
    except Exception:
        return None
    return amount if amount > 0 else None


def render_market_chart(symbol, df, st_line=None, signal_times=None, height=430):
    """Render one independent TradingView-style chart for one market only."""
    if df is None or len(df) == 0:
        st.info(f"{symbol}: chart data unavailable")
        return

    d = df.copy()
    if "time" in d.columns:
        d["dt"] = pd.to_datetime(d["time"], unit="s", utc=True)
    elif "datetime" in d.columns:
        d["dt"] = pd.to_datetime(d["datetime"], utc=True)
    else:
        d["dt"] = pd.RangeIndex(len(d))

    fig = go.Figure()

    required = {"open", "high", "low", "close"}
    if required.issubset(d.columns):
        fig.add_trace(go.Candlestick(
            x=d["dt"],
            open=d["open"],
            high=d["high"],
            low=d["low"],
            close=d["close"],
            name=f"{symbol} Price",
            increasing_line_width=1,
            decreasing_line_width=1,
        ))

    if st_line is not None:
        try:
            st_series = pd.Series(st_line, index=d.index)
            fig.add_trace(go.Scatter(
                x=d["dt"],
                y=st_series,
                mode="lines",
                name="SuperTrend 10,3",
                line=dict(width=2),
                connectgaps=False,
            ))
        except Exception:
            pass

    # Optional signal markers. signal_times can be a list of
    # {"time": ..., "side": ..., "price": ...} dictionaries.
    if signal_times:
        buys, sells = [], []
        for s in signal_times:
            try:
                row = {
                    "dt": pd.to_datetime(s["time"], unit="s", utc=True)
                    if isinstance(s["time"], (int, float))
                    else pd.to_datetime(s["time"], utc=True),
                    "price": float(s["price"]),
                }
                if str(s.get("side", "")).lower() == "buy":
                    buys.append(row)
                elif str(s.get("side", "")).lower() == "sell":
                    sells.append(row)
            except Exception:
                continue

        if buys:
            fig.add_trace(go.Scatter(
                x=[x["dt"] for x in buys],
                y=[x["price"] for x in buys],
                mode="markers",
                name="BUY",
                marker=dict(symbol="triangle-up", size=12),
            ))
        if sells:
            fig.add_trace(go.Scatter(
                x=[x["dt"] for x in sells],
                y=[x["price"] for x in sells],
                mode="markers",
                name="SELL",
                marker=dict(symbol="triangle-down", size=12),
            ))

    fig.update_layout(
        title=f"{symbol} — 1 Minute | SuperTrend 10,3",
        height=height,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=45, b=10),
        hovermode="x unified",
        legend=dict(orientation="h"),
    )
    fig.update_xaxes(showgrid=True)
    fig.update_yaxes(showgrid=True)
    st.plotly_chart(fig, use_container_width=True, key=f"tv_chart_{symbol}")

# --------------------------------------------------------
    # CANDLES
    # --------------------------------------------------------

    candle_response = api.candles()

    if not candle_response.get("success"):
        st.error(
            f"❌ {symbol} candle data failed: "
            f"{candle_response.get('error', '-')}"
        )
        return

    df = make_dataframe(
        candle_response
    )

    if df.empty:
        st.error(
            f"❌ {symbol}: candle data empty."
        )
        return

    # ONLY COMPLETED 1-MINUTE CANDLES
    current_candle_start = (
        int(time.time()) // CANDLE_SECONDS
    ) * CANDLE_SECONDS

    df = df[
        df["time"] < current_candle_start
    ].copy().reset_index(drop=True)

    if len(df) < ATR_PERIOD + 5:
        st.error(
            f"❌ {symbol}: enough completed candles "
            f"are not available."
        )
        return

    df = calculate_supertrend(df)

    last = df.iloc[-1]

    current_close = float(
        last["close"]
    )

    current_st = float(
        last["SUPERTREND"]
    )

    current_atr = number(
        last.get("ATR"),
        0
    )

    # Market-specific T1/T2/T3 from the same confirmed 1-minute ATR.
    t1_mult, t2_mult, t3_mult = TARGET_ATR_MULTIPLIERS.get(
        symbol,
        (1.0, 1.5, 2.0)
    )

    current_direction_value = int(
        last["ST_DIRECTION"]
    )

    if current_direction_value == -1:
        current_direction = (
            "BUY / BULLISH 🟢"
        )
    else:
        current_direction = (
            "SELL / BEARISH 🔴"
        )

    signal_rows = df[
        df["SIGNAL"].isin(
            ["BUY", "SELL"]
        )
    ].copy()

    if signal_rows.empty:
        signal = ""
        signal_price = current_close
        signal_st = current_st
        signal_time = indian_time(
            last["time"]
        )
        signal_epoch = int(
            last["time"]
        )
    else:
        current_entry = signal_rows.iloc[-1]

        signal = str(
            current_entry["SIGNAL"]
        )

        signal_price = float(
            current_entry["close"]
        )

        signal_st = float(
            current_entry["SUPERTREND"]
        )

        signal_epoch = int(
            current_entry["time"]
        )

        signal_time = indian_time(
            signal_epoch
        )

    # --------------------------------------------------------
    # TICKER
    # --------------------------------------------------------

    ticker_response = api.ticker()
    ticker_result = get_result(
        ticker_response
    )

    live_price = None

    if isinstance(ticker_result, dict):
        for key in (
            "close",
            "last_price",
            "mark_price",
            "spot_price"
        ):
            live_price = number(
                ticker_result.get(key)
            )

            if live_price is not None:
                break

    # --------------------------------------------------------
    # TOP STATUS
    # --------------------------------------------------------

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "LIVE PRICE",
            show_price(live_price)
        )

    with c2:
        st.metric(
            "1M DIRECTION",
            current_direction
        )

    with c3:
        st.metric(
            "1M SUPERTREND 10,3",
            show_price(current_st)
        )

    with c4:
        st.metric(
            "CONFIRMED SIGNAL",
            signal or "WAIT"
        )

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    if signal == "BUY":
        st.success(
            f"🟢 BUY | Entry "
            f"{show_price(signal_price)} | "
            f"ST {show_price(signal_st)} | "
            f"{signal_time}"
        )

    elif signal == "SELL":
        st.error(
            f"🔴 SELL | Entry "
            f"{show_price(signal_price)} | "
            f"ST {show_price(signal_st)} | "
            f"{signal_time}"
        )

    else:
        st.info(
            "No new confirmed 1-minute SuperTrend flip."
        )

    # --------------------------------------------------------
    # PRODUCT LOT INFORMATION
    # --------------------------------------------------------

    contract_size = (
        product.get("contract_value")
        or product.get("contract_size")
        or product.get("lot_size")
        or "-"
    )

    st.write(
        f"**1 Lot = 1 Contract** | "
        f"Delta contract value/size: **{contract_size}**"
    )

    # --------------------------------------------------------
    # REAL POSITION
    # --------------------------------------------------------

    position_response = api.position()

    if position_response.get("success"):
        pos = position_from_response(
            position_response
        )

        pos_size = number(
            pos.get("size"),
            0
        )

        pos_entry = number(
            pos.get("entry_price")
        )

        pos_pnl = number(
            pos.get("unrealized_pnl"),
            0
        )

        if pos_size > 0:
            pos_side = "LONG 🟢"
        elif pos_size < 0:
            pos_side = "SHORT 🔴"
        else:
            pos_side = "FLAT ⚪"

        p1, p2, p3 = st.columns(3)

        with p1:
            st.metric(
                "POSITION",
                pos_side
            )

        with p2:
            st.metric(
                "SIZE",
                abs(pos_size)
            )

        with p3:
            st.metric(
                "UNREALIZED P&L",
                f"{pos_pnl:,.2f}"
            )

    else:
        st.warning(
            "Position check failed."
        )

    # --------------------------------------------------------
    # OPEN ORDERS
    # --------------------------------------------------------

    open_response = api.open_orders()

    open_orders = get_result(
        open_response
    )

    if not isinstance(open_orders, list):
        open_orders = []

    # --------------------------------------------------------
    # CLOSED ORDERS
    # --------------------------------------------------------

    closed_response = api.closed_orders()

    closed_orders = get_result(
        closed_response
    )

    if not isinstance(closed_orders, list):
        closed_orders = []

    # --------------------------------------------------------
    # ORDER LOGIC
    # --------------------------------------------------------

    if (
        not REMOTE_TRADING
        or not owner_connected
        or signal not in ["BUY", "SELL"]
    ):
        if signal in ["BUY", "SELL"]:
            st.info(
                f"{symbol}: नया real order अभी नहीं भेजा गया."
            )

    else:
        order_side = (
            "buy"
            if signal == "BUY"
            else "sell"
        )

        # Entry offset remains consistent with the existing dashboard.
        if signal == "BUY":
            limit_price = (
                signal_price + BUY_OFFSET
            )
            target_1 = (
                limit_price + current_atr * t1_mult
            )
            target_2 = (
                limit_price + current_atr * t2_mult
            )
            target_3 = (
                limit_price + current_atr * t3_mult
            )
        else:
            limit_price = (
                signal_price + SELL_OFFSET
            )
            target_1 = (
                limit_price - current_atr * t1_mult
            )
            target_2 = (
                limit_price - current_atr * t2_mult
            )
            target_3 = (
                limit_price - current_atr * t3_mult
            )

        # With exactly 1 lot, the same lot cannot be split into three
        # independently executable partial TPs. T1 is therefore the
        # attached executable TP; T2/T3 are extended target levels.
        target_price = target_1

        # Independent trailing distance from the same confirmed ATR.
        trailing_amount = (
            abs(float(current_atr))
            * float(TRAIL_ATR_MULTIPLIERS.get(symbol, 0.50))
        )

        stable_id = (
            f"STB_{'B' if signal == 'BUY' else 'S'}_"
            f"{pid}_"
            f"{signal_epoch}"
        )

        # Delta client_order_id max-length safety.
        stable_id = stable_id[:32]

        same_direction_open = False
        exact_signal_seen = False

        for order in open_orders:
            side = str(
                order.get("side", "")
            ).lower()

            if side == order_side:
                same_direction_open = True

            client_id = str(
                order.get(
                    "client_order_id",
                    ""
                )
            )

            if stable_id in client_id:
                exact_signal_seen = True

        for order in closed_orders:
            client_id = str(
                order.get(
                    "client_order_id",
                    ""
                )
            )

            if stable_id in client_id:
                exact_signal_seen = True

        # ----------------------------------------------------
        # OPPOSITE OPEN ORDER CANCEL
        # ----------------------------------------------------

        opposite_side = (
            "sell"
            if order_side == "buy"
            else "buy"
        )

        cleanup_ok = True

        for order in open_orders:
            side = str(
                order.get("side", "")
            ).lower()

            if side != opposite_side:
                continue

            order_id = order.get("id")

            if order_id is None:
                continue

            cancel_result = api.cancel_order(
                order_id
            )

            if cancel_result.get("success"):
                st.warning(
                    f"🔄 {symbol}: old opposite "
                    f"{side.upper()} order cancelled."
                )
            else:
                cleanup_ok = False
                st.error(
                    f"🛑 {symbol}: opposite order "
                    f"could not be cancelled."
                )

        # ----------------------------------------------------
        # OPPOSITE POSITION CLOSE
        # ----------------------------------------------------

        current_position_response = api.position()

        if not current_position_response.get(
            "success"
        ):
            cleanup_ok = False

        else:
            current_position_size = (
                position_size(
                    current_position_response
                )
            )

            opposite_position = (
                (
                    signal == "BUY"
                    and current_position_size < 0
                )
                or
                (
                    signal == "SELL"
                    and current_position_size > 0
                )
            )

            if opposite_position:
                close_side = (
                    "buy"
                    if current_position_size < 0
                    else "sell"
                )

                close_size = int(
                    abs(current_position_size)
                )

                if close_size > 0:
                    close_result = (
                        api.place_market_reduce_only(
                            close_side,
                            close_size,
                            (
                                f"CLS_{pid}_"
                                f"{signal_epoch}"
                            )[:32]
                        )
                    )

                    if close_result.get(
                        "success"
                    ):
                        st.warning(
                            f"🔄 {symbol}: old opposite "
                            f"position closed."
                        )
                    else:
                        cleanup_ok = False
                        st.error(
                            f"🛑 {symbol}: old opposite "
                            f"position could not be closed."
                        )

        # ----------------------------------------------------
        # TARGET PLAN
        # ----------------------------------------------------

        st.write(
            f"**{symbol} Target Plan:** "
            f"T1 **{show_price(target_1)}** | "
            f"T2 **{show_price(target_2)}** | "
            f"T3 **{show_price(target_3)}** | "
            f"TRAIL **{show_price(trailing_amount)}**"
        )

        st.caption(
            f"ATR: {show_price(current_atr)} | "
            f"Multipliers: {t1_mult}× / {t2_mult}× / {t3_mult}× | "
            f"1 lot: T1 is the executable attached TP"
        )

        # ----------------------------------------------------
        # FINAL DUPLICATE GUARD
        # ----------------------------------------------------

        if not cleanup_ok:
            st.error(
                f"🛑 {symbol}: NEW ORDER BLOCKED — "
                f"cleanup/verification failed."
            )

        elif same_direction_open:
            st.success(
                f"🛡️ {symbol}: duplicate blocked — "
                f"{signal} order already open."
            )

        elif exact_signal_seen:
            st.success(
                f"🛡️ {symbol}: duplicate blocked — "
                f"this confirmed 1-minute signal was already processed."
            )

        else:
            # ------------------------------------------------
            # ONE LOT ONLY
            # ------------------------------------------------

            result = api.place_limit_order(
                side=order_side,
                size=lot_size,
                limit_price=limit_price,
                client_order_id=stable_id,
                trailing_amount=trailing_amount
            )

            if result.get("success"):
                order_data = result.get(
                    "result",
                    {}
                )

                order_id = (
                    order_data.get("id")
                    if isinstance(
                        order_data,
                        dict
                    )
                    else "-"
                )

                st.success(
                    f"✅ {symbol}: REAL {signal} "
                    f"1-LOT LIMIT ORDER SENT"
                )

                st.write(
                    f"Order ID: **{order_id}** | "
                    f"Entry: **{show_price(limit_price)}** | "
                    f"T1/TP: **{show_price(target_1)}** | "
                    f"T2: **{show_price(target_2)}** | "
                    f"T3: **{show_price(target_3)}** | "
                    f"Qty: **1 lot**"
                )

            else:
                st.error(
                    f"❌ {symbol}: REAL ORDER FAILED — "
                    f"{result.get('error', result)}"
                )

    # --------------------------------------------------------
    # CURRENT OPEN ORDER TABLE
    # --------------------------------------------------------

    if open_orders:
        rows = []

        for order in open_orders:
            rows.append({
                "Order ID": order.get("id", "-"),
                "Side": str(
                    order.get("side", "")
                ).upper(),
                "Type": order.get(
                    "order_type",
                    order.get("type", "-")
                ),
                "Price": show_price(
                    order.get("limit_price")
                ),
                "Size": order.get(
                    "size",
                    "-"
                ),
                "TP": show_price(
                    order.get(
                        "bracket_take_profit_price"
                    )
                ),
                "State": order.get(
                    "state",
                    "-"
                ),
                "Client ID": order.get(
                    "client_order_id",
                    "-"
                )
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info(
            f"{symbol}: No open orders."
        )

    # --------------------------------------------------------
    # LAST SIGNAL / MARKET SUMMARY
    # --------------------------------------------------------

    summary = pd.DataFrame([
        {
            "Market": symbol,
            "Product ID": pid,
            "Timeframe": "1 Minute",
            "SuperTrend": "10,3 HL2",
            "Direction": current_direction,
            "Signal": signal or "WAIT",
            "Signal Price": show_price(
                signal_price
            ),
            "T1": show_price(
                (
                    signal_price + current_atr * t1_mult
                    if signal == "BUY"
                    else signal_price - current_atr * t1_mult
                )
            ),
            "T2": show_price(
                (
                    signal_price + current_atr * t2_mult
                    if signal == "BUY"
                    else signal_price - current_atr * t2_mult
                )
            ),
            "T3": show_price(
                (
                    signal_price + current_atr * t3_mult
                    if signal == "BUY"
                    else signal_price - current_atr * t3_mult
                )
            ),
            "SuperTrend Price": show_price(
                signal_st
            ),
            "Live Price": show_price(
                live_price
            ),
            "Order Qty": "1 Lot",
        }
    ])

    st.dataframe(
        summary,
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# CREATE TWO COMPLETELY INDEPENDENT API ENGINES
# ============================================================

if OWNER_API_KEY and OWNER_API_SECRET:

    api_clients = {}

    for market_name, market in MARKETS.items():
        if market_name not in product_info:
            continue

        api_clients[market_name] = DeltaAPI(
            OWNER_API_KEY,
            OWNER_API_SECRET,
            market["symbol"],
            product_info[market_name]["product_id"]
        )

    # ========================================================
    # BTC — INDEPENDENT 1-MINUTE ENGINE
    # ========================================================

    if "BTCUSD" in api_clients:
        process_market(
            "BTCUSD",
            MARKETS["BTCUSD"],
            product_info["BTCUSD"],
            api_clients["BTCUSD"]
        )

    # ========================================================
    # XAUTUSD — INDEPENDENT 1-MINUTE ENGINE
    # ========================================================

    if "XAUTUSD" in api_clients:
        process_market(
            "XAUTUSD",
            MARKETS["XAUTUSD"],
            product_info["XAUTUSD"],
            api_clients["XAUTUSD"]
        )


# ============================================================
# FINAL STATUS
# ============================================================

st.divider()

st.subheader(
    "⚡ FINAL LIVE TRADING STATUS"
)

status_rows = []

for market_name, market in MARKETS.items():
    info = product_info.get(
        market_name
    )

    status_rows.append({
        "Market": market["symbol"],
        "Product ID": (
            info["product_id"]
            if info
            else "NOT VERIFIED"
        ),
        "Timeframe": "1 Minute",
        "SuperTrend": "ATR 10 / 3.0 / HL2",
        "Order": "1 Lot",
        "Real Trading": (
            "ACTIVE"
            if (
                REMOTE_TRADING
                and owner_connected
                and info
            )
            else "BLOCKED"
        )
    })

st.dataframe(
    pd.DataFrame(status_rows),
    use_container_width=True,
    hide_index=True
)

st.caption(
    "Dashboard Time: "
    + now_ist_text()
)

time.sleep(
    max(1, REFRESH_SECONDS)
)

st.rerun()


# ============================================================
# TWO INDEPENDENT TRADINGVIEW-STYLE CHARTS
# BTCUSD and XAUTUSD are rendered separately; their data,
# SuperTrend, ATR and signals are never mixed.
# ============================================================
def show_two_market_charts():
    market_frames = {}
    market_st = {}
    market_signals = {}

    # Pick up already-existing per-market DataFrames from the app
    # without changing the trading engine.
    for _sym in ("BTCUSD", "XAUTUSD"):
        if _sym in globals():
            obj = globals()[_sym]
            if isinstance(obj, pd.DataFrame):
                market_frames[_sym] = obj

    # Common dictionary naming patterns used by market engines.
    for _name in ("market_data", "market_dfs", "dataframes", "dfs"):
        _obj = globals().get(_name)
        if isinstance(_obj, dict):
            for _sym in ("BTCUSD", "XAUTUSD"):
                if isinstance(_obj.get(_sym), pd.DataFrame):
                    market_frames[_sym] = _obj[_sym]

    for _name in ("supertrend_lines", "market_supertrends", "st_lines"):
        _obj = globals().get(_name)
        if isinstance(_obj, dict):
            for _sym in ("BTCUSD", "XAUTUSD"):
                if _sym in _obj:
                    market_st[_sym] = _obj[_sym]

    for _name in ("market_signals", "signals_by_market", "signals"):
        _obj = globals().get(_name)
        if isinstance(_obj, dict):
            for _sym in ("BTCUSD", "XAUTUSD"):
                if _sym in _obj and isinstance(_obj[_sym], (list, tuple)):
                    market_signals[_sym] = _obj[_sym]

    # Render only when corresponding DataFrame already exists.
    # No trading/order state is changed by this display block.
    if "BTCUSD" in market_frames:
        render_market_chart(
            "BTCUSD",
            market_frames["BTCUSD"],
            market_st.get("BTCUSD"),
            market_signals.get("BTCUSD"),
        )
    else:
        st.info("BTCUSD: chart data is not available in the current market dataframe.")

    if "XAUTUSD" in market_frames:
        render_market_chart(
            "XAUTUSD",
            market_frames["XAUTUSD"],
            market_st.get("XAUTUSD"),
            market_signals.get("XAUTUSD"),
        )
    else:
        st.info("XAUTUSD: chart data is not available in the current market dataframe.")


show_two_market_charts()

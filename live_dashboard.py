import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# ============================================================
# SETTINGS
# ============================================================

DELTA_BASE_URL = "https://api.india.delta.exchange"
SYMBOL = "BTCUSD"
RESOLUTION = "5m"

# TradingView reference candle supplied by you
TV_TIME = "11:05 PM"
TV_OPEN = 75670.6
TV_HIGH = 75670.6
TV_LOW = 75405.3
TV_CLOSE = 75507.7

IST = timezone(timedelta(hours=5, minutes=30))

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="SANJAY RANA — Candle Matcher",
    layout="wide"
)

st.title("SANJAY RANA — TradingView / Delta Candle Matcher")

st.caption(
    "5-minute candle • Exact OHLC comparison • Closed candle only"
)

# ============================================================
# DELTA CANDLES
# ============================================================

def get_delta_candles(symbol=SYMBOL, resolution=RESOLUTION, limit=20):

    url = f"{DELTA_BASE_URL}/v2/history/candles"

    end_time = int(datetime.now(timezone.utc).timestamp())
    start_time = end_time - (limit * 5 * 60)

    params = {
        "symbol": symbol,
        "resolution": resolution,
        "start": start_time,
        "end": end_time,
    }

    response = requests.get(
        url,
        params=params,
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    candles = data.get("result", [])

    if not candles:
        return pd.DataFrame()

    rows = []

    for c in candles:

        # Delta normally returns:
        # [time, open, high, low, close, volume]
        if isinstance(c, list):

            rows.append({
                "time": c[0],
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]) if len(c) > 5 else 0,
            })

        elif isinstance(c, dict):

            rows.append({
                "time": c.get("time"),
                "open": float(c.get("open")),
                "high": float(c.get("high")),
                "low": float(c.get("low")),
                "close": float(c.get("close")),
                "volume": float(c.get("volume", 0)),
            })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # ========================================================
    # TIME
    # ========================================================

    df["time"] = pd.to_datetime(
        df["time"],
        unit="s",
        utc=True
    ).dt.tz_convert(IST)

    df = df.sort_values("time").reset_index(drop=True)

    return df


# ============================================================
# EXACT OHLC MATCH
# ============================================================

def ohlc_match(delta_candle):

    checks = {
        "OPEN": delta_candle["open"] == TV_OPEN,
        "HIGH": delta_candle["high"] == TV_HIGH,
        "LOW": delta_candle["low"] == TV_LOW,
        "CLOSE": delta_candle["close"] == TV_CLOSE,
    }

    return checks, all(checks.values())


# ============================================================
# LOAD
# ============================================================

try:

    df = get_delta_candles()

except Exception as e:

    st.error(f"Delta candle error: {e}")
    st.stop()


if df.empty:

    st.error("Delta se candle data nahi mila.")
    st.stop()


# ============================================================
# LAST CLOSED CANDLE
# ============================================================

now = pd.Timestamp.now(tz=IST)

closed_df = df[df["time"] < now].copy()

if closed_df.empty:

    st.warning("Closed candle available nahi hai.")
    st.stop()


last = closed_df.iloc[-1]


# ============================================================
# CURRENT DELTA CANDLE
# ============================================================

st.subheader("Latest Delta Candle")

c1, c2, c3, c4, c5 = st.columns(5)

c1.metric(
    "TIME",
    last["time"].strftime("%d-%m-%Y %I:%M:%S %p")
)

c2.metric(
    "OPEN",
    f'{last["open"]:.1f}'
)

c3.metric(
    "HIGH",
    f'{last["high"]:.1f}'
)

c4.metric(
    "LOW",
    f'{last["low"]:.1f}'
)

c5.metric(
    "CLOSE",
    f'{last["close"]:.1f}'
)


# ============================================================
# TRADINGVIEW REFERENCE
# ============================================================

st.divider()

st.subheader("TradingView Reference Candle")

tv1, tv2, tv3, tv4, tv5 = st.columns(5)

tv1.metric("TIME", TV_TIME)
tv2.metric("OPEN", f"{TV_OPEN:.1f}")
tv3.metric("HIGH", f"{TV_HIGH:.1f}")
tv4.metric("LOW", f"{TV_LOW:.1f}")
tv5.metric("CLOSE", f"{TV_CLOSE:.1f}")


# ============================================================
# MATCH CHECK
# ============================================================

st.divider()

st.subheader("OHLC Matching")

checks, matched = ohlc_match(last)

m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "OPEN",
    "MATCH" if checks["OPEN"] else "MISMATCH"
)

m2.metric(
    "HIGH",
    "MATCH" if checks["HIGH"] else "MISMATCH"
)

m3.metric(
    "LOW",
    "MATCH" if checks["LOW"] else "MISMATCH"
)

m4.metric(
    "CLOSE",
    "MATCH" if checks["CLOSE"] else "MISMATCH"
)


# ============================================================
# RESULT
# ============================================================

if matched:

    st.success(
        "✅ EXACT OHLC MATCH — TradingView aur Delta candle same hai."
    )

else:

    st.error(
        "❌ OHLC MATCH NAHI HUI — SuperTrend signal ko valid match nahi maana jayega."
    )

    st.write("### Difference")

    comparison = pd.DataFrame({
        "Value": [
            "Open",
            "High",
            "Low",
            "Close"
        ],
        "TradingView": [
            TV_OPEN,
            TV_HIGH,
            TV_LOW,
            TV_CLOSE
        ],
        "Delta": [
            last["open"],
            last["high"],
            last["low"],
            last["close"]
        ],
        "Difference": [
            last["open"] - TV_OPEN,
            last["high"] - TV_HIGH,
            last["low"] - TV_LOW,
            last["close"] - TV_CLOSE
        ]
    })

    st.dataframe(
        comparison,
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# LAST 10 CLOSED CANDLES
# ============================================================

st.divider()

st.subheader("Last 10 Closed Delta Candles")

show = closed_df.tail(10).copy()

show["time"] = show["time"].dt.strftime(
    "%d-%m-%Y %I:%M %p"
)

show = show[
    [
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]
]

st.dataframe(
    show,
    use_container_width=True,
    hide_index=True
)

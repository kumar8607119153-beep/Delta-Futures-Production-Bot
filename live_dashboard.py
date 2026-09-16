# ============================================================
# SANJAY RANA — HEIKIN ASHI CANDLE MATCH TEST
# ============================================================

import time
import requests
import pandas as pd
import streamlit as st


# ============================================================
# SETTINGS
# ============================================================

BASE_URL = "https://api.india.delta.exchange"

SYMBOL = "BTCUSD"

TIMEFRAME = "5m"

CANDLE_SECONDS = 300


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="SANJAY RANA — HA Candle Match",
    page_icon="🕯️",
    layout="wide"
)

st.title("🕯️ SANJAY RANA — HEIKIN ASHI CANDLE MATCH")

st.caption(
    "BTCUSD | 5 Minute | HA Open / High / Low / Close"
)


# ============================================================
# GET DELTA CANDLES
# ============================================================

def get_delta_candles():

    end = int(time.time())

    start = end - (500 * CANDLE_SECONDS)

    url = (
        BASE_URL
        + "/v2/history/candles"
    )

    params = {
        "symbol": SYMBOL,
        "resolution": TIMEFRAME,
        "start": start,
        "end": end
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=15
        )

        data = response.json()

        if not data.get("success"):

            st.error(
                f"Delta candle error: {data}"
            )

            return pd.DataFrame()

        result = data.get(
            "result",
            []
        )

        rows = []

        for candle in result:

            try:

                rows.append({

                    "time": int(
                        candle["time"]
                    ),

                    "open": float(
                        candle["open"]
                    ),

                    "high": float(
                        candle["high"]
                    ),

                    "low": float(
                        candle["low"]
                    ),

                    "close": float(
                        candle["close"]
                    )

                })

            except Exception:

                continue


        if not rows:

            return pd.DataFrame()


        df = pd.DataFrame(rows)


        df = (
            df
            .drop_duplicates(
                subset=["time"]
            )
            .sort_values("time")
            .reset_index(drop=True)
        )


        return df


    except Exception as e:

        st.error(
            f"Delta request error: {e}"
        )

        return pd.DataFrame()


# ============================================================
# GET CANDLES
# ============================================================

df = get_delta_candles()


if df.empty:

    st.error(
        "Delta se candle data nahi mila."
    )

    st.stop()


# ============================================================
# REMOVE CURRENT OPEN CANDLE
# ============================================================

current_candle_start = (

    int(time.time())
    // CANDLE_SECONDS

) * CANDLE_SECONDS


df = df[
    df["time"]
    < current_candle_start
].copy()


df = (
    df
    .sort_values("time")
    .reset_index(drop=True)
)


if df.empty:

    st.error(
        "Koi completed 5-minute candle nahi mili."
    )

    st.stop()


# ============================================================
# HEIKIN ASHI CALCULATION
# ============================================================
#
# TradingView:
#
# ha_handle = ticker.heikinashi(syminfo.tickerid)
#
# HA Close:
# (Open + High + Low + Close) / 4
#
# HA Open:
# first candle  = (Open + Close) / 2
# next candles   = previous HA Open + previous HA Close / 2
#
# HA High:
# max(Real High, HA Open, HA Close)
#
# HA Low:
# min(Real Low, HA Open, HA Close)
#
# ============================================================


df["HA_CLOSE"] = (

    df["open"]
    + df["high"]
    + df["low"]
    + df["close"]

) / 4.0


df["HA_OPEN"] = float("nan")


for i in range(len(df)):

    if i == 0:

        df.loc[i, "HA_OPEN"] = (

            df.loc[i, "open"]
            + df.loc[i, "close"]

        ) / 2.0

    else:

        df.loc[i, "HA_OPEN"] = (

            df.loc[i - 1, "HA_OPEN"]
            + df.loc[i - 1, "HA_CLOSE"]

        ) / 2.0


df["HA_HIGH"] = pd.concat(
    [
        df["high"],
        df["HA_OPEN"],
        df["HA_CLOSE"]
    ],
    axis=1
).max(axis=1)


df["HA_LOW"] = pd.concat(
    [
        df["low"],
        df["HA_OPEN"],
        df["HA_CLOSE"]
    ],
    axis=1
).min(axis=1)


# ============================================================
# DISPLAY LAST CLOSED HA CANDLE
# ============================================================

last = df.iloc[-1]


signal_time = pd.to_datetime(
    int(last["time"]),
    unit="s",
    utc=True
).tz_convert(
    "Asia/Kolkata"
).strftime(
    "%Y-%m-%d %H:%M:%S IST"
)


st.divider()

st.subheader("🕯️ LAST CLOSED HEIKIN ASHI CANDLE")


col1, col2, col3, col4 = st.columns(4)


with col1:

    st.metric(
        "HA OPEN",
        f"{last['HA_OPEN']:,.2f}"
    )


with col2:

    st.metric(
        "HA HIGH",
        f"{last['HA_HIGH']:,.2f}"
    )


with col3:

    st.metric(
        "HA LOW",
        f"{last['HA_LOW']:,.2f}"
    )


with col4:

    st.metric(
        "HA CLOSE",
        f"{last['HA_CLOSE']:,.2f}"
    )


st.write(
    f"**Candle Time:** {signal_time}"
)


# ============================================================
# LAST 20 HA CANDLES
# ============================================================

st.divider()

st.subheader("📊 LAST 20 CLOSED HA CANDLES")


display_df = df.tail(20).copy()


display_df["TIME"] = pd.to_datetime(
    display_df["time"],
    unit="s",
    utc=True
).dt.tz_convert(
    "Asia/Kolkata"
).dt.strftime(
    "%Y-%m-%d %H:%M:%S"
)


display_df = display_df[
    [
        "TIME",
        "HA_OPEN",
        "HA_HIGH",
        "HA_LOW",
        "HA_CLOSE"
    ]
].copy()


display_df.columns = [
    "TIME",
    "HA OPEN",
    "HA HIGH",
    "HA LOW",
    "HA CLOSE"
]


st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True
)


# ============================================================
# IMPORTANT
# ============================================================

st.info(
    "⚠️ अभी केवल Heikin Ashi OHLC बनाया गया है। "
    "SuperTrend / BUY / SELL / Order logic अभी नहीं लगाया गया है। "
    "पहले HA candle को TradingView से match करें।"
)


# ============================================================
# AUTO REFRESH
# ============================================================

time.sleep(5)

st.rerun()

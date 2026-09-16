# ============================================================
# SANJAY RANA — SUPERTREND 10/3 TEST DASHBOARD
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

ATR_PERIOD = 10

FACTOR = 3.0


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="SANJAY RANA — SuperTrend 10/3",
    page_icon="📈",
    layout="wide"
)

st.title("📈 SANJAY RANA — SUPERTREND 10/3")

st.caption(
    "BTCUSD | 5 Minute | ATR 10 | Factor 3.0 | "
    "Confirmed Closed Candle"
)


# ============================================================
# DELTA CANDLES
# ============================================================

def get_candles():

    end = int(time.time())

    start = (
        end
        - (500 * CANDLE_SECONDS)
    )

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
                f"Delta error: {data}"
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
            f"Delta candle request error: {e}"
        )

        return pd.DataFrame()


# ============================================================
# SUPERTREND 10/3
# ============================================================

def calculate_supertrend(df):

    df = df.copy()


    high = df["high"].astype(float)

    low = df["low"].astype(float)

    close = df["close"].astype(float)


    # --------------------------------------------------------
    # TRUE RANGE
    # --------------------------------------------------------

    previous_close = close.shift(1)


    tr1 = (
        high
        - low
    )


    tr2 = (
        high
        - previous_close
    ).abs()


    tr3 = (
        low
        - previous_close
    ).abs()


    tr = pd.concat(
        [
            tr1,
            tr2,
            tr3
        ],
        axis=1
    ).max(axis=1)


    # --------------------------------------------------------
    # ATR = TradingView WILDER RMA
    # --------------------------------------------------------

    atr = pd.Series(
        float("nan"),
        index=df.index
    )


    if len(df) >= ATR_PERIOD:

        atr.iloc[
            ATR_PERIOD - 1
        ] = (
            tr.iloc[
                :ATR_PERIOD
            ].mean()
        )


        for i in range(
            ATR_PERIOD,
            len(df)
        ):

            atr.iloc[i] = (

                atr.iloc[i - 1]
                * (ATR_PERIOD - 1)

                + tr.iloc[i]

            ) / ATR_PERIOD


    # --------------------------------------------------------
    # BASIC BANDS
    # --------------------------------------------------------

    hl2 = (
        high
        + low
    ) / 2.0


    upper_basic = (
        hl2
        + FACTOR * atr
    )


    lower_basic = (
        hl2
        - FACTOR * atr
    )


    # --------------------------------------------------------
    # FINAL BANDS
    # --------------------------------------------------------

    upper = pd.Series(
        float("nan"),
        index=df.index
    )


    lower = pd.Series(
        float("nan"),
        index=df.index
    )


    direction = pd.Series(
        float("nan"),
        index=df.index
    )


    supertrend = pd.Series(
        float("nan"),
        index=df.index
    )


    # TradingView ta.supertrend()
    #
    # direction:
    # -1 = bullish
    #  1 = bearish
    #
    # Initial direction = 1

    previous_direction = 1


    for i in range(
        len(df)
    ):

        if pd.isna(
            atr.iloc[i]
        ):

            continue


        # ----------------------------------------------------
        # FIRST VALID BAR
        # ----------------------------------------------------

        if i == 0:

            upper.iloc[i] = (
                upper_basic.iloc[i]
            )

            lower.iloc[i] = (
                lower_basic.iloc[i]
            )

            direction.iloc[i] = 1

            supertrend.iloc[i] = (
                upper.iloc[i]
            )

            previous_direction = 1

            continue


        previous_upper = (
            upper.iloc[i - 1]
        )


        previous_lower = (
            lower.iloc[i - 1]
        )


        previous_close_value = (
            close.iloc[i - 1]
        )


        # ----------------------------------------------------
        # UPPER BAND
        # ----------------------------------------------------

        if (
            upper_basic.iloc[i]
            < previous_upper

            or

            previous_close_value
            > previous_upper
        ):

            upper.iloc[i] = (
                upper_basic.iloc[i]
            )

        else:

            upper.iloc[i] = (
                previous_upper
            )


        # ----------------------------------------------------
        # LOWER BAND
        # ----------------------------------------------------

        if (
            lower_basic.iloc[i]
            > previous_lower

            or

            previous_close_value
            < previous_lower
        ):

            lower.iloc[i] = (
                lower_basic.iloc[i]
            )

        else:

            lower.iloc[i] = (
                previous_lower
            )


        # ----------------------------------------------------
        # DIRECTION
        #
        # TradingView:
        #
        # direction == -1 → bullish
        # direction ==  1 → bearish
        # ----------------------------------------------------

        if (
            previous_direction == 1

            and

            close.iloc[i]
            > previous_upper
        ):

            current_direction = -1


        elif (
            previous_direction == -1

            and

            close.iloc[i]
            < previous_lower
        ):

            current_direction = 1


        else:

            current_direction = (
                previous_direction
            )


        direction.iloc[i] = (
            current_direction
        )


        # ----------------------------------------------------
        # SUPERTREND LINE
        # ----------------------------------------------------

        if current_direction == -1:

            supertrend.iloc[i] = (
                lower.iloc[i]
            )

        else:

            supertrend.iloc[i] = (
                upper.iloc[i]
            )


        previous_direction = (
            current_direction
        )


    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    df["ATR"] = atr

    df["SUPERTREND"] = (
        supertrend
    )

    df["DIRECTION"] = (
        direction
    )


    # --------------------------------------------------------
    # SIGNAL = ONLY DIRECTION FLIP
    # --------------------------------------------------------

    df["BUY_SIGNAL"] = (

        (direction == -1)

        &

        (direction.shift(1) == 1)

    )


    df["SELL_SIGNAL"] = (

        (direction == 1)

        &

        (direction.shift(1) == -1)

    )


    return df


# ============================================================
# LOAD CANDLES
# ============================================================

df = get_candles()


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


if len(df) < ATR_PERIOD + 10:

    st.error(
        "SuperTrend calculation ke liye "
        "enough closed candles nahi hain."
    )

    st.stop()


# ============================================================
# CALCULATE SUPERTREND
# ============================================================

df = calculate_supertrend(
    df
)


# ============================================================
# LAST CLOSED CANDLE
# ============================================================

last = df.iloc[-1]


# ============================================================
# CURRENT DIRECTION
# ============================================================

if last["DIRECTION"] == -1:

    current_signal = "BUY"

else:

    current_signal = "SELL"


# ============================================================
# LAST FLIP SIGNAL
# ============================================================

last_buy = df[
    df["BUY_SIGNAL"]
]


last_sell = df[
    df["SELL_SIGNAL"]
]


if not last_buy.empty and not last_sell.empty:

    last_buy_time = (
        last_buy.iloc[-1]["time"]
    )

    last_sell_time = (
        last_sell.iloc[-1]["time"]
    )


    if last_buy_time > last_sell_time:

        signal = "BUY"

        signal_row = (
            last_buy.iloc[-1]
        )

    else:

        signal = "SELL"

        signal_row = (
            last_sell.iloc[-1]
        )


elif not last_buy.empty:

    signal = "BUY"

    signal_row = (
        last_buy.iloc[-1]
    )


elif not last_sell.empty:

    signal = "SELL"

    signal_row = (
        last_sell.iloc[-1]
    )


else:

    signal = current_signal

    signal_row = last


# ============================================================
# SIGNAL TIME
# ============================================================

signal_time = pd.to_datetime(
    int(signal_row["time"]),
    unit="s",
    utc=True
).tz_convert(
    "Asia/Kolkata"
).strftime(
    "%Y-%m-%d %H:%M:%S IST"
)


# ============================================================
# SIGNAL CANDLE PRICE
# ============================================================

signal_candle_price = float(
    signal_row["close"]
)


# ============================================================
# CURRENT LIVE PRICE
# ============================================================

try:

    ticker_url = (
        BASE_URL
        + f"/v2/tickers/{SYMBOL}"
    )


    ticker_response = requests.get(
        ticker_url,
        timeout=10
    )


    ticker_data = (
        ticker_response.json()
    )


    live_price = float(
        ticker_data["result"]["close"]
    )


except Exception:

    live_price = float(
        last["close"]
    )


# ============================================================
# DISPLAY — ONLY SIGNAL INFORMATION
# ============================================================

if signal == "BUY":

    st.success(
        "🟢 SUPERTREND SIGNAL: BUY"
    )

else:

    st.error(
        "🔴 SUPERTREND SIGNAL: SELL"
    )


st.write(
    f"SUPERTREND SIGNAL PRICE: "
    f"{signal_candle_price:,.2f}"
)


st.write(
    f"LIVE PRICE: "
    f"{live_price:,.2f}"
)


st.write(
    f"SIGNAL TIME: "
    f"{signal_time}"
)


# ============================================================
# AUTO REFRESH
# ============================================================

time.sleep(5)

st.rerun()

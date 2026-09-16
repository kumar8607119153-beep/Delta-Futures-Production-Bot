# ============================================================
# SANJAY RANA — ST HA 10/3
# CHART ONLY
# ============================================================

import time
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# ============================================================
# SETTINGS
# ============================================================

BASE_URL = "https://api.india.delta.exchange"
SYMBOL = "BTCUSD"

TIMEFRAME = "5m"
CANDLE_SECONDS = 300

ATR_PERIOD = 10
FACTOR = 3.0

CANDLE_COUNT = 500


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="SANJAY RANA — ST HA 10/3",
    page_icon="📈",
    layout="wide"
)

st.title("📈 SANJAY RANA — ST HA 10/3")

st.caption(
    "5 Minute | Heikin Ashi | ATR 10 | Factor 3.0 | "
    "Confirmed Candle"
)


# ============================================================
# DELTA CANDLES
# ============================================================

def get_candles():

    end = int(time.time())

    start = end - (
        CANDLE_COUNT * CANDLE_SECONDS
    )

    url = f"{BASE_URL}/v2/history/candles"

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
            return pd.DataFrame()

        rows = []

        for c in data.get("result", []):

            try:

                rows.append({
                    "time": int(c["time"]),
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"])
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

    except Exception as e:

        st.error(f"Delta candle error: {e}")

        return pd.DataFrame()


# ============================================================
# ONLY CLOSED 5-MINUTE CANDLES
# ============================================================

df = get_candles()

if df.empty:

    st.error("Delta se candle data nahi mila.")

    st.stop()


current_candle_start = (
    int(time.time()) // CANDLE_SECONDS
) * CANDLE_SECONDS


df = df[
    df["time"] < current_candle_start
].copy()


df = df.reset_index(drop=True)


if len(df) < ATR_PERIOD + 10:

    st.error(
        "ST HA calculation ke liye enough candles nahi hain."
    )

    st.stop()


# ============================================================
# HEIKIN ASHI
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
# HA TRUE RANGE
# ============================================================

previous_ha_close = df["HA_CLOSE"].shift(1)

tr1 = (
    df["HA_HIGH"]
    - df["HA_LOW"]
)

tr2 = (
    df["HA_HIGH"]
    - previous_ha_close
).abs()

tr3 = (
    df["HA_LOW"]
    - previous_ha_close
).abs()


df["TR"] = pd.concat(
    [tr1, tr2, tr3],
    axis=1
).max(axis=1)


# ============================================================
# TRADINGVIEW ta.atr(10)
# = RMA / WILDER
# ============================================================

df["ATR"] = float("nan")


if len(df) >= ATR_PERIOD:

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
            previous_atr
            * (ATR_PERIOD - 1)
            + current_tr
        ) / ATR_PERIOD


# ============================================================
# ST HA
# EXACT CORE LOGIC
# ============================================================

df["HA_HL2"] = (
    df["HA_HIGH"]
    + df["HA_LOW"]
) / 2.0


df["MUP"] = (
    df["HA_HL2"]
    - FACTOR * df["ATR"]
)


df["MDN"] = (
    df["HA_HL2"]
    + FACTOR * df["ATR"]
)


df["MTrendUp"] = float("nan")
df["MTrendDown"] = float("nan")
df["MTrend"] = float("nan")
df["MTsl"] = float("nan")


# Pine starts these variables at 0.0
previous_trend_up = 0.0
previous_trend_down = 0.0
previous_trend = 0.0


for i in range(len(df)):

    atr = df.loc[i, "ATR"]

    if pd.isna(atr):
        continue


    mup = df.loc[i, "MUP"]
    mdn = df.loc[i, "MDN"]

    mclose = df.loc[
        i,
        "HA_CLOSE"
    ]


    # --------------------------------------------------------
    # Pine:
    #
    # MTrendUp :=
    # Mclose[1] > MTrendUp[1]
    # ? math.max(MUp, MTrendUp[1])
    # : MUp
    # --------------------------------------------------------

    if i > 0:

        previous_mclose = df.loc[
            i - 1,
            "HA_CLOSE"
        ]

    else:

        previous_mclose = float("nan")


    if (
        i > 0
        and previous_mclose > previous_trend_up
    ):

        current_trend_up = max(
            mup,
            previous_trend_up
        )

    else:

        current_trend_up = mup


    # --------------------------------------------------------
    # Pine:
    #
    # MTrendDown :=
    # Mclose[1] < MTrendDown[1]
    # ? math.min(MDn, MTrendDown[1])
    # : MDn
    # --------------------------------------------------------

    if (
        i > 0
        and previous_mclose < previous_trend_down
    ):

        current_trend_down = min(
            mdn,
            previous_trend_down
        )

    else:

        current_trend_down = mdn


    # --------------------------------------------------------
    # Pine:
    #
    # MTrend :=
    # Mclose > MTrendDown[1] ? 1 :
    # Mclose < MTrendUp[1] ? -1 :
    # nz(MTrend[1], 1)
    # --------------------------------------------------------

    if i > 0:

        if mclose > previous_trend_down:

            current_trend = 1.0

        elif mclose < previous_trend_up:

            current_trend = -1.0

        else:

            current_trend = (
                previous_trend
                if previous_trend != 0
                else 1.0
            )

    else:

        current_trend = 1.0


    current_tsl = (
        current_trend_up
        if current_trend == 1
        else current_trend_down
    )


    df.loc[
        i,
        "MTrendUp"
    ] = current_trend_up


    df.loc[
        i,
        "MTrendDown"
    ] = current_trend_down


    df.loc[
        i,
        "MTrend"
    ] = current_trend


    df.loc[
        i,
        "MTsl"
    ] = current_tsl


    previous_trend_up = current_trend_up
    previous_trend_down = current_trend_down
    previous_trend = current_trend


# ============================================================
# SIGNALS
#
# EXACT Pine:
#
# golong  := close > MTsl
# goshort := close < MTsl
#
# IMPORTANT:
# FINAL SIGNAL USES REAL CANDLE CLOSE,
# NOT HA CLOSE.
# ============================================================

df["GOLONG"] = (
    df["close"]
    > df["MTsl"]
)


df["GOSHORT"] = (
    df["close"]
    < df["MTsl"]
)


df["SIGNAL"] = ""


df.loc[
    df["GOLONG"],
    "SIGNAL"
] = "BUY"


df.loc[
    df["GOSHORT"],
    "SIGNAL"
] = "SELL"


# ============================================================
# SIGNAL CHANGE
# ============================================================

df["SIGNAL_CHANGE"] = (
    df["SIGNAL"]
    != df["SIGNAL"].shift(1)
)


df.loc[
    df["SIGNAL"].isin(["BUY", "SELL"])
    & df["SIGNAL_CHANGE"],
    "NEW_SIGNAL"
] = True


df["NEW_SIGNAL"] = (
    df["SIGNAL_CHANGE"]
    & df["SIGNAL"].isin(["BUY", "SELL"])
)


# ============================================================
# LAST CANDLE
# ============================================================

last = df.iloc[-1]

last_signal = last["SIGNAL"]

last_close = float(
    last["close"]
)

last_tsl = float(
    last["MTsl"]
)


# ============================================================
# STATUS
# ============================================================

if last_signal == "BUY":

    st.success(
        f"🟢 BUY | REAL CLOSE: {last_close:,.2f} "
        f"| ST HA: {last_tsl:,.2f}"
    )

elif last_signal == "SELL":

    st.error(
        f"🔴 SELL | REAL CLOSE: {last_close:,.2f} "
        f"| ST HA: {last_tsl:,.2f}"
    )

else:

    st.info("No signal")


# ============================================================
# CHART DATA
# ============================================================

df["datetime"] = pd.to_datetime(
    df["time"],
    unit="s",
    utc=True
)


# ============================================================
# PLOTLY CHART
# ============================================================

fig = go.Figure()


# ------------------------------------------------------------
# REAL CANDLES
# ------------------------------------------------------------

fig.add_trace(
    go.Candlestick(

        x=df["datetime"],

        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],

        name="BTCUSD",

        increasing_line_color="green",
        decreasing_line_color="red"
    )
)


# ------------------------------------------------------------
# GREEN ST LINE
# ------------------------------------------------------------

green_line = df[
    df["MTrend"] == 1
]


fig.add_trace(
    go.Scatter(

        x=green_line["datetime"],
        y=green_line["MTsl"],

        mode="lines",

        name="ST HA BUY",

        line=dict(
            color="green",
            width=2
        )
    )
)


# ------------------------------------------------------------
# RED ST LINE
# ------------------------------------------------------------

red_line = df[
    df["MTrend"] == -1
]


fig.add_trace(
    go.Scatter(

        x=red_line["datetime"],
        y=red_line["MTsl"],

        mode="lines",

        name="ST HA SELL",

        line=dict(
            color="red",
            width=2
        )
    )
)


# ============================================================
# BUY MARKERS
# ============================================================

buy_points = df[
    df["NEW_SIGNAL"]
    & (df["SIGNAL"] == "BUY")
]


fig.add_trace(
    go.Scatter(

        x=buy_points["datetime"],
        y=buy_points["close"],

        mode="markers+text",

        name="BUY",

        text=["BUY"] * len(buy_points),

        textposition="bottom center",

        marker=dict(
            size=10,
            symbol="triangle-up",
            color="green"
        )
    )
)


# ============================================================
# SELL MARKERS
# ============================================================

sell_points = df[
    df["NEW_SIGNAL"]
    & (df["SIGNAL"] == "SELL")
]


fig.add_trace(
    go.Scatter(

        x=sell_points["datetime"],
        y=sell_points["close"],

        mode="markers+text",

        name="SELL",

        text=["SELL"] * len(sell_points),

        textposition="top center",

        marker=dict(
            size=10,
            symbol="triangle-down",
            color="red"
        )
    )
)


# ============================================================
# LAYOUT
# ============================================================

fig.update_layout(

    height=750,

    xaxis_rangeslider_visible=False,

    template="plotly_white",

    margin=dict(
        l=10,
        r=10,
        t=40,
        b=10
    ),

    legend=dict(
        orientation="h"
    )
)


fig.update_xaxes(
    showgrid=True
)

fig.update_yaxes(
    showgrid=True
)


st.plotly_chart(
    fig,
    use_container_width=True
)


# ============================================================
# LAST CLOSED CANDLE
# ============================================================

st.subheader("🕯️ LAST CLOSED 5-MINUTE CANDLE")

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "REAL CLOSE",
    f"{last_close:,.2f}"
)

c2.metric(
    "ST HA",
    f"{last_tsl:,.2f}"
)

c3.metric(
    "DIRECTION",
    last_signal
)

c4.metric(
    "ATR",
    f"{float(last['ATR']):,.2f}"
)


# ============================================================
# RECENT SIGNALS
# ============================================================

st.subheader("📊 RECENT ST HA SIGNALS")

signal_history = df[
    df["NEW_SIGNAL"]
    & df["SIGNAL"].isin(["BUY", "SELL"])
][
    [
        "datetime",
        "SIGNAL",
        "close",
        "MTsl",
        "ATR"
    ]
].tail(30).copy()


signal_history["datetime"] = (
    signal_history["datetime"]
    .dt.tz_convert("Asia/Kolkata")
    .dt.strftime("%Y-%m-%d %H:%M:%S IST")
)


signal_history["close"] = (
    signal_history["close"]
    .map(lambda x: f"{x:,.2f}")
)


signal_history["MTsl"] = (
    signal_history["MTsl"]
    .map(lambda x: f"{x:,.2f}")
)


signal_history["ATR"] = (
    signal_history["ATR"]
    .map(lambda x: f"{x:,.2f}")
)


st.dataframe(
    signal_history.iloc[::-1],
    use_container_width=True,
    hide_index=True
)


# ============================================================
# AUTO REFRESH
# ============================================================

time.sleep(5)

st.rerun()

# ============================================================
# SUPERTREND 10/3
# TradingView ta.supertrend(factor, atrLen)
# ============================================================

ATR_PERIOD = 10
MULTIPLIER = 3.0


def calculate_supertrend(df):

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    hl2 = (high + low) / 2.0

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    # ATR = Wilder RMA(10)
    atr = pd.Series(
        float("nan"),
        index=df.index
    )

    if len(df) >= ATR_PERIOD:

        atr.iloc[ATR_PERIOD - 1] = (
            tr.iloc[:ATR_PERIOD].mean()
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

    upper_basic = (
        hl2 + MULTIPLIER * atr
    )

    lower_basic = (
        hl2 - MULTIPLIER * atr
    )

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

    for i in range(len(df)):

        if pd.isna(atr.iloc[i]):
            continue

        if i == 0:

            upper.iloc[i] = upper_basic.iloc[i]
            lower.iloc[i] = lower_basic.iloc[i]

            direction.iloc[i] = 1

            supertrend.iloc[i] = upper.iloc[i]

            continue

        prev_upper = upper.iloc[i - 1]
        prev_lower = lower.iloc[i - 1]
        prev_close = close.iloc[i - 1]

        # Final Upper Band
        if (
            upper_basic.iloc[i] < prev_upper
            or prev_close > prev_upper
        ):

            upper.iloc[i] = upper_basic.iloc[i]

        else:

            upper.iloc[i] = prev_upper

        # Final Lower Band
        if (
            lower_basic.iloc[i] > prev_lower
            or prev_close < prev_lower
        ):

            lower.iloc[i] = lower_basic.iloc[i]

        else:

            lower.iloc[i] = prev_lower

        prev_direction = direction.iloc[i - 1]

        # TradingView ta.supertrend direction
        if (
            prev_direction == 1
            and close.iloc[i] > prev_upper
        ):

            direction.iloc[i] = -1

        elif (
            prev_direction == -1
            and close.iloc[i] < prev_lower
        ):

            direction.iloc[i] = 1

        else:

            direction.iloc[i] = prev_direction

        # SuperTrend line
        if direction.iloc[i] == -1:

            supertrend.iloc[i] = lower.iloc[i]

        else:

            supertrend.iloc[i] = upper.iloc[i]

    df["SUPERTREND"] = supertrend
    df["DIRECTION"] = direction

    # TradingView:
    # direction == -1 = bullish
    # direction ==  1 = bearish

    df["BUY_SIGNAL"] = (
        (direction == -1)
        & (direction.shift(1) == 1)
    )

    df["SELL_SIGNAL"] = (
        (direction == 1)
        & (direction.shift(1) == -1)
    )

    return df


# ============================================================
# GET DELTA CANDLES
# ============================================================

candle_response = api.candles()

df = make_dataframe(candle_response)

if df.empty:

    st.error(
        "Delta se candle data nahi mila."
    )

    st.stop()


# ============================================================
# ONLY CLOSED 5-MINUTE CANDLES
# ============================================================

current_candle_start = (
    int(time.time()) // CANDLE_SECONDS
) * CANDLE_SECONDS

df = df[
    df["time"] < current_candle_start
].copy()

df = df.reset_index(drop=True)


if len(df) < ATR_PERIOD + 5:

    st.error(
        "SuperTrend ke liye enough candles nahi hain."
    )

    st.stop()


# ============================================================
# RUN SUPERTREND
# ============================================================

df = calculate_supertrend(df)


# ============================================================
# LAST CLOSED CANDLE
# ============================================================

last_candle = df.iloc[-1]


# ============================================================
# CURRENT SUPERTREND DIRECTION
# ============================================================

if last_candle["DIRECTION"] == -1:

    signal = "BUY"

else:

    signal = "SELL"


# ============================================================
# LAST FLIP SIGNAL
# ============================================================

if last_candle["BUY_SIGNAL"]:

    signal = "BUY"

elif last_candle["SELL_SIGNAL"]:

    signal = "SELL"


# ============================================================
# SUPERTREND PRICE
# ============================================================

supertrend_price = last_candle["SUPERTREND"]


# ============================================================
# TWO LINES ONLY
# ============================================================

st.write(
    "SUPERTREND SIGNAL: "
    + (
        "🟢 BUY"
        if signal == "BUY"
        else "🔴 SELL"
    )
)

st.write(
    "SUPERTREND PRICE: "
    + show_price(supertrend_price)
  )

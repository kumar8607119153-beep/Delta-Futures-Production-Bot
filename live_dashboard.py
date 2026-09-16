# ============================================================
# SUPERTREND 10/3 — EXACT SIGNAL BLOCK
# ============================================================

ATR_PERIOD = 10
MULTIPLIER = 3.0


def calculate_supertrend(df):

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    # TradingView ta.supertrend()
    hl2 = (high + low) / 2.0

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    # Wilder RMA — same ATR basis
    atr = pd.Series(float("nan"), index=df.index)

    if len(df) >= ATR_PERIOD:
        atr.iloc[ATR_PERIOD - 1] = (
            tr.iloc[:ATR_PERIOD].mean()
        )

        for i in range(
            ATR_PERIOD,
            len(df)
        ):
            atr.iloc[i] = (
                atr.iloc[i - 1] * (ATR_PERIOD - 1)
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

        if (
            upper_basic.iloc[i] < prev_upper
            or prev_close > prev_upper
        ):
            upper.iloc[i] = upper_basic.iloc[i]
        else:
            upper.iloc[i] = prev_upper

        if (
            lower_basic.iloc[i] > prev_lower
            or prev_close < prev_lower
        ):
            lower.iloc[i] = lower_basic.iloc[i]
        else:
            lower.iloc[i] = prev_lower

        prev_direction = direction.iloc[i - 1]

        if (
            prev_direction == 1
            and close.iloc[i] > upper.iloc[i - 1]
        ):
            direction.iloc[i] = -1

        elif (
            prev_direction == -1
            and close.iloc[i] < lower.iloc[i - 1]
        ):
            direction.iloc[i] = 1

        else:
            direction.iloc[i] = prev_direction

        if direction.iloc[i] == -1:
            supertrend.iloc[i] = lower.iloc[i]
        else:
            supertrend.iloc[i] = upper.iloc[i]

    df["SUPERTREND"] = supertrend
    df["DIRECTION"] = direction

    # Pine:
    # direction == -1 → BUY
    # direction == 1  → SELL

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
# CALCULATE
# ============================================================

df = calculate_supertrend(df)


# ============================================================
# LAST CLOSED CANDLE SIGNAL
# ============================================================

last_candle = df.iloc[-1]

if last_candle["BUY_SIGNAL"]:

    signal = "BUY"

elif last_candle["SELL_SIGNAL"]:

    signal = "SELL"

else:

    signal = (
        "BUY"
        if last_candle["DIRECTION"] == -1
        else "SELL"
    )


# ============================================================
# ONLY TWO DISPLAY LINES
# ============================================================

st.write(
    f"SUPERTREND SIGNAL: "
    f"{'🟢 BUY' if signal == 'BUY' else '🔴 SELL'}"
)

st.write(
    f"SUPERTREND PRICE: "
    f"{show_price(last_candle['SUPERTREND'])}"
  )

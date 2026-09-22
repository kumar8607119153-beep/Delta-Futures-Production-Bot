import os
import csv
import json
import time
import hmac
import hashlib
import signal
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# DELTA FUTURES PRODUCTION BOT
# ============================================================
# SYMBOL       : BTCUSD
# TIMEFRAME    : 1 MINUTE
# SUPERTREND   : ATR 10 / MULTIPLIER 3
# ENTRY        : BUY  -50
#                SELL +50
# TP           : DISABLED
# ============================================================

BASE_URL = os.getenv(
    "DELTA_BASE_URL",
    "https://api.india.delta.exchange"
).rstrip("/")

API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")

SYMBOL = "BTCUSD"

# IMPORTANT: 1 MINUTE
INTERVAL = "1m"

ATR_PERIOD = 10
ST_MULTIPLIER = Decimal("3")
ENTRY_OFFSET = Decimal("50")

ENTRY_SIZE = 3

# API checking frequency
POLL_SECONDS = 5

CANDLE_LOOKBACK = 250
HEARTBEAT_SECONDS = 30

RECORD_DIR = "trading_records"
JSON_RECORD_FILE = os.path.join(
    RECORD_DIR, "trading_record.jsonl"
)
CSV_RECORD_FILE = os.path.join(
    RECORD_DIR, "trading_record.csv"
)

STATE_FILE = "delta_bot_state.json"

PRODUCT_ID = None
TICK_SIZE = Decimal("0.5")
CONTRACT_VALUE = Decimal("0.001")
MIN_ORDER_SIZE = 1

RUNNER_IP = "UNKNOWN"
STOP = False

SESSION_ID = datetime.now(
    timezone.utc
).strftime("%Y%m%d_%H%M%S")

session = requests.Session()

session.headers.update({
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "delta-india-production-bot/1m"
})


# ============================================================
# TIME / LOG
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def log(*args):
    print(
        utc_now(),
        "|",
        *args,
        flush=True
    )


# ============================================================
# TRADING RECORD
# ============================================================

def record(event, **data):

    item = {
        "timestamp_utc": utc_now(),
        "session_id": SESSION_ID,
        "event": event,
        **data
    }

    os.makedirs(
        RECORD_DIR,
        exist_ok=True
    )

    try:
        with open(
            JSON_RECORD_FILE,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(
                json.dumps(
                    item,
                    ensure_ascii=False,
                    default=str
                ) + "\n"
            )

    except Exception as e:
        log(
            "JSON RECORD ERROR:",
            str(e)
        )

    fields = [
        "timestamp_utc",
        "session_id",
        "event",
        "symbol",
        "side",
        "signal",
        "price",
        "signal_close",
        "entry_price",
        "quantity",
        "position_size",
        "order_id",
        "order_state",
        "filled_size",
        "remaining_size",
        "candle_id",
        "trend",
        "current_price",
        "runner_ip",
        "message"
    ]

    try:

        exists = os.path.exists(
            CSV_RECORD_FILE
        )

        row = {
            field: item.get(
                field,
                ""
            )
            for field in fields
        }

        with open(
            CSV_RECORD_FILE,
            "a",
            newline="",
            encoding="utf-8"
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=fields
            )

            if not exists:
                writer.writeheader()

            writer.writerow(row)

    except Exception as e:

        log(
            "CSV RECORD ERROR:",
            str(e)
        )


# ============================================================
# CREDENTIALS
# ============================================================

def require_credentials():

    if not API_KEY:
        raise RuntimeError(
            "DELTA_API_KEY secret is missing"
        )

    if not API_SECRET:
        raise RuntimeError(
            "DELTA_API_SECRET secret is missing"
        )

    if not BASE_URL.startswith(
        "https://api.india.delta.exchange"
    ):
        raise RuntimeError(
            "Production safety check failed: "
            "DELTA_BASE_URL must be "
            "https://api.india.delta.exchange"
        )


# ============================================================
# PUBLIC IP
# ============================================================

def get_runner_ip():

    global RUNNER_IP

    try:

        response = requests.get(
            "https://api.ipify.org",
            timeout=10
        )

        response.raise_for_status()

        RUNNER_IP = response.text.strip()

        log(
            "PUBLIC IP:",
            RUNNER_IP
        )

        record(
            "PUBLIC_IP",
            symbol=SYMBOL,
            runner_ip=RUNNER_IP
        )

    except Exception as e:

        RUNNER_IP = "UNKNOWN"

        log(
            "PUBLIC IP ERROR:",
            str(e)
        )

        record(
            "PUBLIC_IP_ERROR",
            symbol=SYMBOL,
            message=str(e)
        )

    return RUNNER_IP


# ============================================================
# DELTA SIGNATURE
# ============================================================

def generate_signature(
    method,
    timestamp,
    path,
    query_string,
    body
):

    message = (
        method.upper()
        + timestamp
        + path
        + query_string
        + body
    )

    return hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()


# ============================================================
# PRIVATE REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
    body=None,
    retries=5
):

    require_credentials()

    params = params or {}
    body = body or {}

    body_string = (
        json.dumps(
            body,
            separators=(",", ":"),
            ensure_ascii=False
        )
        if body
        else ""
    )

    query_string = (
        "?" + urlencode(
            params,
            doseq=True
        )
        if params
        else ""
    )

    for attempt in range(retries):

        timestamp = str(
            int(time.time())
        )

        signature = generate_signature(
            method,
            timestamp,
            path,
            query_string,
            body_string
        )

        headers = {
            "Accept":
                "application/json",

            "Content-Type":
                "application/json",

            "User-Agent":
                "delta-india-production-bot/1m",

            "api-key":
                API_KEY,

            "timestamp":
                timestamp,

            "signature":
                signature
        }

        try:

            response = session.request(
                method.upper(),
                BASE_URL + path,
                params=params,
                data=body_string,
                headers=headers,
                timeout=(5, 25)
            )

            try:
                data = response.json()
            except ValueError:
                raise RuntimeError(
                    "Invalid JSON response"
                )

            if response.status_code == 429:

                log(
                    "RATE LIMIT - retry"
                )

                time.sleep(5)
                continue

            if response.status_code >= 400:

                raise RuntimeError(
                    f"Delta HTTP "
                    f"{response.status_code}: "
                    f"{data}"
                )

            if (
                isinstance(data, dict)
                and data.get("success") is False
            ):

                raise RuntimeError(
                    f"Delta API error: {data}"
                )

            return data

        except Exception as e:

            log(
                "API RETRY",
                attempt + 1,
                "/",
                retries,
                "|",
                str(e)
            )

            record(
                "API_RETRY",
                symbol=SYMBOL,
                attempt=attempt + 1,
                message=str(e)
            )

            if attempt == retries - 1:
                raise

            time.sleep(
                min(
                    2 ** attempt,
                    20
                )
            )

    raise RuntimeError(
        "Delta API request failed"
    )


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(
    path,
    params=None,
    retries=5
):

    for attempt in range(retries):

        try:

            response = session.get(
                BASE_URL + path,
                params=params or {},
                timeout=(5, 20)
            )

            try:
                data = response.json()
            except ValueError:
                raise RuntimeError(
                    "Invalid public JSON response"
                )

            if response.status_code == 429:

                time.sleep(5)
                continue

            if response.status_code >= 400:

                raise RuntimeError(
                    f"Public HTTP "
                    f"{response.status_code}: "
                    f"{data}"
                )

            if (
                isinstance(data, dict)
                and data.get("success") is False
            ):

                raise RuntimeError(
                    f"Delta public API error: "
                    f"{data}"
                )

            return data

        except Exception:

            if attempt == retries - 1:
                raise

            time.sleep(
                min(
                    2 ** attempt,
                    20
                )
            )

    raise RuntimeError(
        "Public request failed"
    )


# ============================================================
# PRODUCT
# ============================================================

def load_product():

    global PRODUCT_ID
    global TICK_SIZE
    global CONTRACT_VALUE
    global MIN_ORDER_SIZE

    data = public_get(
        f"/v2/products/{SYMBOL}"
    )

    product = data.get(
        "result",
        data
    )

    if not isinstance(
        product,
        dict
    ):
        raise RuntimeError(
            "Invalid product response"
        )

    PRODUCT_ID = int(
        product["id"]
    )

    TICK_SIZE = Decimal(
        str(
            product.get(
                "tick_size",
                "0.5"
            )
        )
    )

    CONTRACT_VALUE = Decimal(
        str(
            product.get(
                "contract_value",
                "0.001"
            )
        )
    )

    try:

        MIN_ORDER_SIZE = int(
            Decimal(
                str(
                    product.get(
                        "contract_unit_min_size",
                        1
                    )
                )
            )
        )

    except Exception:

        MIN_ORDER_SIZE = 1

    if MIN_ORDER_SIZE < 1:
        MIN_ORDER_SIZE = 1

    log(
        "PRODUCT LOADED",
        "| SYMBOL:", SYMBOL,
        "| PRODUCT ID:", PRODUCT_ID,
        "| TICK:", TICK_SIZE,
        "| CONTRACT:", CONTRACT_VALUE,
        "| MIN QTY:", MIN_ORDER_SIZE
    )


# ============================================================
# PRICE
# ============================================================

def round_price(price):

    value = Decimal(
        str(price)
    )

    return (
        value / TICK_SIZE
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * TICK_SIZE


def price_str(price):

    return format(
        round_price(price),
        "f"
    )


# ============================================================
# CURRENT PRICE
# ============================================================

def get_current_price():

    data = public_get(
        f"/v2/tickers/{SYMBOL}"
    )

    result = data.get(
        "result",
        data
    )

    if not isinstance(
        result,
        dict
    ):
        return None

    for key in (
        "close",
        "last_traded_price",
        "last_price",
        "mark_price"
    ):

        value = result.get(key)

        if value is not None:

            try:
                return Decimal(
                    str(value)
                )
            except Exception:
                pass

    return None


# ============================================================
# 1 MINUTE CANDLES
# ============================================================

def get_candles(
    count=CANDLE_LOOKBACK
):

    now = int(
        time.time()
    )

    start = (
        now
        - (count + 5) * 60
    )

    data = public_get(
        "/v2/history/candles",
        {
            "resolution":
                INTERVAL,

            "symbol":
                SYMBOL,

            "start":
                start,

            "end":
                now
        }
    )

    rows = data.get(
        "result",
        []
    )

    if not rows:

        raise RuntimeError(
            "No 1-minute candles received"
        )

    df = pd.DataFrame(rows)

    required = [
        "time",
        "open",
        "high",
        "low",
        "close"
    ]

    for column in required:

        if column not in df.columns:

            raise RuntimeError(
                f"Missing candle column: {column}"
            )

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df = (
        df
        .dropna(
            subset=required
        )
        .sort_values("time")
        .drop_duplicates("time")
        .reset_index(drop=True)
    )

    return df


# ============================================================
# SUPERTREND
# ============================================================

def calculate_supertrend(df):

    d = df.copy()

    high = d["high"]
    low = d["low"]
    close = d["close"]

    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (
                high - previous_close
            ).abs(),
            (
                low - previous_close
            ).abs()
        ],
        axis=1
    ).max(axis=1)

    atr = true_range.ewm(
        alpha=1 / ATR_PERIOD,
        adjust=False,
        min_periods=ATR_PERIOD
    ).mean()

    hl2 = (
        high + low
    ) / 2

    basic_upper = (
        hl2
        + float(ST_MULTIPLIER)
        * atr
    )

    basic_lower = (
        hl2
        - float(ST_MULTIPLIER)
        * atr
    )

    final_upper = [
        float("nan")
    ] * len(d)

    final_lower = [
        float("nan")
    ] * len(d)

    trend = [0] * len(d)

    for i in range(len(d)):

        if pd.isna(
            atr.iloc[i]
        ):
            continue

        if (
            i == 0
            or pd.isna(
                atr.iloc[i - 1]
            )
        ):

            final_upper[i] = (
                basic_upper.iloc[i]
            )

            final_lower[i] = (
                basic_lower.iloc[i]
            )

            trend[i] = 1

            continue

        final_upper[i] = (
            basic_upper.iloc[i]
            if (
                basic_upper.iloc[i]
                < final_upper[i - 1]
                or
                close.iloc[i - 1]
                > final_upper[i - 1]
            )
            else final_upper[i - 1]
        )

        final_lower[i] = (
            basic_lower.iloc[i]
            if (
                basic_lower.iloc[i]
                > final_lower[i - 1]
                or
                close.iloc[i - 1]
                < final_lower[i - 1]
            )
            else final_lower[i - 1]
        )

        if trend[i - 1] == 1:

            trend[i] = (
                -1
                if close.iloc[i]
                < final_lower[i]
                else 1
            )

        else:

            trend[i] = (
                1
                if close.iloc[i]
                > final_upper[i]
                else -1
            )

    d["atr"] = atr
    d["trend"] = trend

    return d


# ============================================================
# CLOSED 1-MINUTE CANDLE SIGNAL
# ============================================================

def get_confirmed_signal():

    df = get_candles()

    # Current unfinished candle removed.
    current_minute = (
        int(time.time())
        // 60
        * 60
    )

    closed = df[
        df["time"] < current_minute
    ].copy()

    if len(closed) < ATR_PERIOD + 3:
        return None

    st = calculate_supertrend(
        closed
    )

    previous = st.iloc[-2]
    current = st.iloc[-1]

    signal_value = None

    if (
        int(previous["trend"]) == -1
        and
        int(current["trend"]) == 1
    ):
        signal_value = "BUY"

    elif (
        int(previous["trend"]) == 1
        and
        int(current["trend"]) == -1
    ):
        signal_value = "SELL"

    candle_id = int(
        current["time"]
    )

    candle_open = Decimal(
        str(current["open"])
    )

    candle_high = Decimal(
        str(current["high"])
    )

    candle_low = Decimal(
        str(current["low"])
    )

    candle_close = Decimal(
        str(current["close"])
    )

    log(
        "1-MIN CLOSED CANDLE",
        "| ID:", candle_id,
        "| O:", candle_open,
        "| H:", candle_high,
        "| L:", candle_low,
        "| C:", candle_close,
        "| TREND:",
        (
            "BULLISH"
            if int(current["trend"]) == 1
            else "BEARISH"
        ),
        "| SIGNAL:",
        signal_value or "NONE"
    )

    record(
        "CLOSED_1M_CANDLE",
        symbol=SYMBOL,
        candle_id=candle_id,
        trend=int(
            current["trend"]
        ),
        signal=signal_value,
        signal_close=str(
            candle_close
        ),
        message=(
            f"O={candle_open}, "
            f"H={candle_high}, "
            f"L={candle_low}, "
            f"C={candle_close}"
        )
    )

    return {
        "signal":
            signal_value,

        "close":
            candle_close,

        "open":
            candle_open,

        "high":
            candle_high,

        "low":
            candle_low,

        "candle_id":
            candle_id,

        "trend":
            int(
                current["trend"]
            )
    }


# ============================================================
# POSITION
# ============================================================
# ============================================================
# POSITION
# ============================================================

def get_position():

    data = signed_request(
        "GET",
        "/v2/positions",
        {
            "product_id":
                PRODUCT_ID
        }
    )

    result = data.get(
        "result",
        data
    )

    if isinstance(
        result,
        list
    ):

        result = next(
            (
                item
                for item in result
                if int(
                    item.get(
                        "product_id",
                        PRODUCT_ID
                    )
                ) == PRODUCT_ID
            ),
            {}
        )

    if not isinstance(
        result,
        dict
    ):

        return 0, Decimal("0")

    try:

        size = int(
            Decimal(
                str(
                    result.get(
                        "size",
                        0
                    )
                )
            )
        )

    except Exception:

        size = 0

    try:

        entry_price = Decimal(
            str(
                result.get(
                    "entry_price",
                    "0"
                )
            )
        )

    except Exception:

        entry_price = Decimal("0")

    return size, entry_price


# ============================================================
# OPEN ORDERS
# ============================================================

def get_open_orders():

    data = signed_request(
        "GET",
        "/v2/orders",
        {
            "product_ids":
                str(PRODUCT_ID),

            "states":
                "open,pending",

            "page_size":
                50
        }
    )

    result = data.get(
        "result",
        []
    )

    if not isinstance(
        result,
        list
    ):
        return []

    return result


# ============================================================
# BOT ENTRY CHECK
# ============================================================

def is_bot_entry(order):

    client_id = str(
        order.get(
            "client_order_id",
            ""
        )
    )

    return (
        client_id.startswith("ENTBUY_")
        or
        client_id.startswith("ENTSELL_")
    )


# ============================================================
# ORDER GET
# ============================================================

def get_order(order_id):

    data = signed_request(
        "GET",
        f"/v2/orders/{int(order_id)}"
    )

    return data.get(
        "result",
        data
    )


# ============================================================
# CANCEL ORDER
# ============================================================

def cancel_order(order):

    order_id = int(
        order["id"]
    )

    side = str(
        order.get(
            "side",
            ""
        )
    ).upper()

    price = order.get(
        "limit_price",
        ""
    )

    quantity = order.get(
        "size",
        ""
    )

    log("")
    log(
        "=================================================="
    )
    log(
        "CANCEL LIMIT ORDER"
    )
    log(
        "ORDER ID    :",
        order_id
    )
    log(
        "SIDE        :",
        side
    )
    log(
        "LIMIT PRICE :",
        price
    )
    log(
        "QUANTITY    :",
        quantity
    )
    log(
        "=================================================="
    )

    record(
        "ORDER_CANCEL_REQUEST",
        symbol=SYMBOL,
        side=side,
        quantity=quantity,
        price=price,
        order_id=order_id,
        message="SuperTrend reversal"
    )

    signed_request(
        "DELETE",
        "/v2/orders",
        body={
            "id":
                order_id,

            "product_id":
                PRODUCT_ID
        }
    )

    deadline = time.time() + 10

    while time.time() < deadline:

        try:

            current = get_order(
                order_id
            )

            state = str(
                current.get(
                    "state",
                    ""
                )
            ).lower()

            if state in (
                "cancelled",
                "canceled",
                "closed"
            ):

                log(
                    "CANCEL CONFIRMED",
                    "| ORDER ID:",
                    order_id,
                    "| STATUS:",
                    state.upper()
                )

                record(
                    "ORDER_CANCELLED",
                    symbol=SYMBOL,
                    side=side,
                    quantity=quantity,
                    price=price,
                    order_id=order_id,
                    order_state=state
                )

                return

        except Exception as e:

            log(
                "CANCEL CHECK:",
                str(e)
            )

        time.sleep(1)

    raise RuntimeError(
        f"Cancel not confirmed: {order_id}"
    )


# ============================================================
# CLIENT ORDER ID
# ============================================================

def new_client_id(prefix):

    return (
        prefix
        + str(
            int(
                time.time() * 1000
            )
        )
    )[:32]


# ============================================================
# SIGNAL + ORDER PREVIEW
# ============================================================
def show_signal_order_preview(signal_data):

    signal_value = signal_data[
        "signal"
    ]

    signal_close = signal_data[
        "close"
    ]

    if signal_value == "BUY":
        side = "buy"
        limit_price = signal_close - ENTRY_OFFSET
        offset = "-50"
        prefix = "ENTBUY_"
    else:
        side = "sell"
        limit_price = signal_close + ENTRY_OFFSET
        offset = "+50"
        prefix = "ENTSELL_"

    limit_price = round_price(
        limit_price
    )

    # Keep the same client-order-id for the preview and the actual order.
    client_id = signal_data.get(
        "client_order_id"
    )

    if not client_id:
        client_id = new_client_id(
            prefix
        )
        signal_data[
            "client_order_id"
        ] = client_id

    log("")
    log(
        "=================================================="
    )
    log(
        "SIGNAL CONFIRMED - REAL ORDER PREVIEW"
    )
    log(
        "=================================================="
    )
    log(
        "SIGNAL       :",
        signal_value
    )
    log(
        "CANDLE ID    :",
        signal_data["candle_id"]
    )
    log(
        "TREND        :",
        (
            "BULLISH"
            if int(signal_data["trend"]) == 1
            else "BEARISH"
        )
    )
    log(
        "SIGNAL PRICE :",
        price_str(signal_close)
    )
    log(
        "EXCHANGE     :",
        "DELTA EXCHANGE"
    )
    log(
        "SYMBOL       :",
        SYMBOL
    )
    log(
        "SIDE         :",
        signal_value
    )
    log(
        "ORDER TYPE   :",
        "LIMIT"
    )
    log(
        "QUANTITY     :",
        ENTRY_SIZE
    )
    log(
        "ENTRY OFFSET :",
        offset
    )
    log(
        "LIMIT PRICE  :",
        price_str(limit_price)
    )
    log(
        "TIME IN FORCE:",
        "GTC"
    )
    log(
        "REDUCE ONLY  :",
        "FALSE"
    )
    log(
        "POST ONLY    :",
        "FALSE"
    )
    log(
        "CLIENT ID    :",
        client_id
    )
    log(
        "=================================================="
    )

    record(
        "SIGNAL_ORDER_PREVIEW",
        symbol=SYMBOL,
        side=signal_value,
        signal=signal_value,
        price=str(limit_price),
        signal_close=str(signal_close),
        entry_price=str(limit_price),
        quantity=ENTRY_SIZE,
        candle_id=signal_data["candle_id"],
        trend=signal_data["trend"],
        runner_ip=RUNNER_IP,
        message=json.dumps({
            "exchange": "DELTA EXCHANGE",
            "order_type": "limit_order",
            "time_in_force": "gtc",
            "reduce_only": False,
            "post_only": False,
            "client_order_id": client_id,
            "side": side,
            "limit_price": price_str(limit_price),
            "size": int(ENTRY_SIZE)
        }, ensure_ascii=False)
    )

    return client_id


# ============================================================
# PLACE LIMIT ENTRY
# ============================================================

def place_limit_entry(
    signal_data
):

    signal_value = signal_data[
        "signal"
    ]

    signal_close = signal_data[
        "close"
    ]

    if signal_value == "BUY":

        side = "buy"

        limit_price = (
            signal_close
            - ENTRY_OFFSET
        )

        prefix = "ENTBUY_"

        offset = "-50"

    else:

        side = "sell"

        limit_price = (
            signal_close
            + ENTRY_OFFSET
        )

        prefix = "ENTSELL_"

        offset = "+50"

    limit_price = round_price(
        limit_price
    )

    client_id = signal_data.get(
        "client_order_id"
    ) or new_client_id(
        prefix
    )

    payload = {
        "product_id":
            PRODUCT_ID,

        "product_symbol":
            SYMBOL,

        "limit_price":
            price_str(limit_price),

        "size":
            int(ENTRY_SIZE),

        "side":
            side,

        "order_type":
            "limit_order",

        "time_in_force":
            "gtc",

        "reduce_only":
            False,

        "post_only":
            False,

        "client_order_id":
            client_id
    }

    log("")
    log(
        "=================================================="
    )
    log(
        "REAL LIMIT ORDER"
    )
    log(
        "=================================================="
    )
    log(
        "SYMBOL       :",
        SYMBOL
    )
    log(
        "SIDE         :",
        signal_value
    )
    log(
        "ORDER TYPE   :",
        "LIMIT"
    )
    log(
        "QUANTITY     :",
        ENTRY_SIZE
    )
    log(
        "SIGNAL PRICE :",
        price_str(signal_close)
    )
    log(
        "ENTRY OFFSET :",
        offset
    )
    log(
        "LIMIT PRICE  :",
        price_str(limit_price)
    )
    log(
        "TIME IN FORCE:",
        "GTC"
    )
    log(
        "REDUCE ONLY  :",
        "FALSE"
    )
    log(
        "POST ONLY    :",
        "FALSE"
    )
    log(
        "CLIENT ID    :",
        client_id
    )
    log(
        "PUBLIC IP    :",
        RUNNER_IP
    )
    log(
        "=================================================="
    )

    record(
        "LIMIT_ORDER_REQUEST",
        symbol=SYMBOL,
        side=signal_value,
        signal=signal_value,
        price=str(limit_price),
        signal_close=str(signal_close),
        entry_price=str(limit_price),
        quantity=ENTRY_SIZE,
        candle_id=signal_data[
            "candle_id"
        ],
        trend=signal_data[
            "trend"
        ],
        runner_ip=RUNNER_IP
    )

    result_data = signed_request(
        "POST",
        "/v2/orders",
        body=payload
    )

    result = result_data.get(
        "result",
        result_data
    )

    order_id = None
    state = ""

    if isinstance(
        result,
        dict
    ):

        order_id = result.get(
            "id"
        )

        state = result.get(
            "state",
            ""
        )

    log("")
    log(
        "LIMIT ORDER SENT"
    )
    log(
        "ORDER ID     :",
        order_id
    )
    log(
        "SIDE         :",
        signal_value
    )
    log(
        "QUANTITY     :",
        ENTRY_SIZE
    )
    log(
        "LIMIT PRICE  :",
        price_str(limit_price)
    )
    log(
        "STATUS       :",
        state or "ACCEPTED"
    )

    record(
        "LIMIT_ORDER_SENT",
        symbol=SYMBOL,
        side=signal_value,
        signal=signal_value,
        price=str(limit_price),
        signal_close=str(signal_close),
        entry_price=str(limit_price),
        quantity=ENTRY_SIZE,
        order_id=order_id,
        order_state=state,
        candle_id=signal_data[
            "candle_id"
        ],
        runner_ip=RUNNER_IP,
        message=json.dumps(
            result,
            ensure_ascii=False,
            default=str
        )[:3000]
    )

    return result


# ============================================================
# SIGNAL PROCESS
# ============================================================

def process_signal(
    signal_data,
    open_orders,
    position_size
):

    if not signal_data:
        return

    signal_value = signal_data.get(
        "signal"
    )

    if not signal_value:
        return

    # Existing real position
    if position_size != 0:

        log(
            "SIGNAL IGNORED"
        )

        log(
            "SIGNAL:",
            signal_value
        )

        log(
            "POSITION:",
            position_size
        )

        record(
            "SIGNAL_IGNORED_POSITION",
            symbol=SYMBOL,
            signal=signal_value,
            position_size=position_size
        )

        return

    entries = [
        order
        for order in open_orders
        if is_bot_entry(order)
    ]

    # Same direction -> no duplicate
    if entries:

        existing_side = str(
            entries[0].get(
                "side",
                ""
            )
        ).upper()

        if existing_side == signal_value:

            log(
                "DUPLICATE BLOCKED"
            )

            log(
                "EXISTING:",
                existing_side
            )

            log(
                "SIGNAL:",
                signal_value
            )

            return

        # Opposite signal -> cancel old
        log("")
        log(
            "=================================================="
        )
        log(
            "SUPERTREND REVERSAL"
        )
        log(
            "OLD ORDER:",
            existing_side
        )
        log(
            "NEW SIGNAL:",
            signal_value
        )
        log(
            "=================================================="
        )

        record(
            "SUPERTREND_REVERSAL",
            symbol=SYMBOL,
            signal=signal_value,
            message=(
                f"old={existing_side}, "
                f"new={signal_value}"
            )
        )

        for order in entries:
            cancel_order(
                order
            )

        # Verify cancellation
        open_orders = get_open_orders()

        remaining = [
            order
            for order in open_orders
            if is_bot_entry(order)
        ]

        if remaining:

            raise RuntimeError(
                "Old order still open; "
                "new order not sent"
            )

    place_limit_entry(
        signal_data
    )


# ============================================================
# STATE
# ============================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return {
            "last_candle": None,
            "last_position": 0,
            "last_entry_price": "0"
        }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return {
            "last_candle": None,
            "last_position": 0,
            "last_entry_price": "0"
        }


def save_state(state):

    temp = STATE_FILE + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            indent=2
        )

    os.replace(
        temp,
        STATE_FILE
    )


# ============================================================
# CONNECTION TEST
# ============================================================

def connection_test():

    log("")
    log(
        "=================================================="
    )
    log(
        "DELTA API CONNECTION"
    )
    log(
        "=================================================="
    )

    # API credentials are NEVER printed.
    log(
        "API KEY    : HIDDEN"
    )

    log(
        "API SECRET : HIDDEN"
    )

    log(
        "PUBLIC IP  :",
        RUNNER_IP
    )

    log(
        "BASE URL   :",
        BASE_URL
    )

    try:

        public_get(
            f"/v2/products/{SYMBOL}"
        )

        log(
            "PUBLIC API : CONNECTED"
        )

    except Exception as e:

        log(
            "PUBLIC API : FAILED"
        )

        log(
            "ERROR:",
            str(e)
        )

        raise

    try:

        position_size, entry_price = (
            get_position()
        )

        log(
            "PRIVATE API: CONNECTED"
        )

        log(
            "STATUS     : CONNECTED"
        )

        log(
            "POSITION   :",
            position_size
        )

        log(
            "ENTRY      :",
            entry_price
        )

        record(
            "API_CONNECTED",
            symbol=SYMBOL,
            runner_ip=RUNNER_IP,
            position_size=position_size,
            entry_price=str(entry_price)
        )

    except Exception as e:

        log(
            "PRIVATE API: FAILED"
        )

        log(
            "STATUS     : FAILED"
        )

        log(
            "ERROR      :",
            str(e)
        )

        record(
            "API_CONNECTION_FAILED",
            symbol=SYMBOL,
            runner_ip=RUNNER_IP,
            message=str(e)
        )

        raise
# ============================================================
# MAIN
# ============================================================

def main():

    global STOP

    require_credentials()

    # IMPORTANT: Do not fetch public IP at startup.
    # The signal and complete proposed exchange order must be shown first.
    load_product()

    state = load_state()

    previous_orders = []

    previous_position = 0

    last_heartbeat = 0

    log("")
    log(
        "=================================================="
    )
    log(
        "1-MINUTE PRODUCTION TRADING STARTED"
    )
    log(
        "SYMBOL       :",
        SYMBOL
    )
    log(
        "TIMEFRAME    :",
        "1m"
    )
    log(
        "ATR          :",
        ATR_PERIOD
    )
    log(
        "MULTIPLIER   :",
        ST_MULTIPLIER
    )
    log(
        "BUY ENTRY    :",
        "CLOSE - 50"
    )
    log(
        "SELL ENTRY   :",
        "CLOSE + 50"
    )
    log(
        "TP           :",
        "DISABLED"
    )
    log(
        "QUANTITY     :",
        ENTRY_SIZE
    )
    log(
        "PUBLIC IP    :",
        "WAITING FOR SIGNAL"
    )
    log(
        "=================================================="
    )

    record(
        "BOT_STARTED",
        symbol=SYMBOL,
        runner_ip=RUNNER_IP,
        message="1-minute production trading started; IP deferred until signal/order preview"
    )

    while not STOP:

        try:

            # ------------------------------------------------
            # 1-MIN CLOSED CANDLE SIGNAL - FIRST
            # ------------------------------------------------

            signal_data = (
                get_confirmed_signal()
            )

            signal_is_new = False

            if signal_data:

                candle_id = (
                    signal_data[
                        "candle_id"
                    ]
                )

                last_candle = (
                    state.get(
                        "last_candle"
                    )
                )

                signal_is_new = (
                    candle_id != last_candle
                    and
                    bool(
                        signal_data.get(
                            "signal"
                        )
                    )
                )

                # ------------------------------------------------
                # SIGNAL -> COMPLETE REAL ORDER DETAIL -> IP
                # ------------------------------------------------
                if signal_is_new:

                    # Do not mark the candle processed until the
                    # normal position/open-order checks have run.
                    show_signal_order_preview(
                        signal_data
                    )

                    log(
                        "SIGNAL/ORDER PREVIEW COMPLETE -> IP FUNCTION STARTING"
                    )

                    # IP is informational/security logging only here.
                    # Failure does NOT itself cancel the trading flow.
                    get_runner_ip()

                    log(
                        "PUBLIC IP STAGE COMPLETE:",
                        RUNNER_IP,
                        "| NEXT: PRIVATE POSITION/ORDER CHECKS"
                    )

            # ------------------------------------------------
            # POSITION
            # ------------------------------------------------

            position_size, entry_price = (
                get_position()
            )

            if position_size != previous_position:

                log(
                    "POSITION CHANGE:",
                    previous_position,
                    "->",
                    position_size
                )

                record(
                    "POSITION_CHANGE",
                    symbol=SYMBOL,
                    position_size=position_size,
                    entry_price=str(
                        entry_price
                    ),
                    message=(
                        f"{previous_position}"
                        f"->{position_size}"
                    )
                )

                previous_position = (
                    position_size
                )

            state[
                "last_position"
            ] = position_size

            state[
                "last_entry_price"
            ] = str(
                entry_price
            )

            # ------------------------------------------------
            # OPEN ORDERS
            # ------------------------------------------------

            open_orders = (
                get_open_orders()
            )

            # ------------------------------------------------
            # PRICE
            # ------------------------------------------------

            current_price = None

            try:

                current_price = (
                    get_current_price()
                )

            except Exception as e:

                log(
                    "PRICE ERROR:",
                    str(e)
                )

            # ------------------------------------------------
            # HEARTBEAT
            # ------------------------------------------------

            now = time.time()

            if (
                now - last_heartbeat
                >= HEARTBEAT_SECONDS
            ):

                log("")
                log(
                    "HEARTBEAT"
                )
                log(
                    "BTCUSD      :",
                    current_price
                )
                log(
                    "POSITION    :",
                    position_size
                )
                log(
                    "ENTRY       :",
                    entry_price
                )
                log(
                    "OPEN ORDERS :",
                    len(open_orders)
                )
                log(
                    "API STATUS  :",
                    "PRIVATE CHECK"
                )
                log(
                    "PUBLIC IP   :",
                    RUNNER_IP
                )

                record(
                    "HEARTBEAT",
                    symbol=SYMBOL,
                    current_price=str(
                        current_price
                    )
                    if current_price is not None
                    else "",
                    position_size=position_size,
                    entry_price=str(
                        entry_price
                    ),
                    runner_ip=RUNNER_IP,
                    message=(
                        f"open_orders="
                        f"{len(open_orders)}"
                    )
                )

                last_heartbeat = now

            # ------------------------------------------------
            # PROCESS SIGNAL AFTER NORMAL SAFETY CHECKS
            # ------------------------------------------------

            if signal_is_new:

                state[
                    "last_candle"
                ] = candle_id

                save_state(
                    state
                )

                process_signal(
                    signal_data,
                    open_orders,
                    position_size
                )

            save_state(
                state
            )

        except Exception as e:

            log("")
            log(
                "=================================================="
            )
            log(
                "LOOP ERROR"
            )
            log(
                "TYPE:",
                type(e).__name__
            )
            log(
                "ERROR:",
                str(e)
            )
            log(
                "BOT WILL RETRY"
            )
            log(
                "=================================================="
            )

            record(
                "LOOP_ERROR",
                symbol=SYMBOL,
                runner_ip=RUNNER_IP,
                message=(
                    f"{type(e).__name__}: "
                    f"{str(e)}"
                )
            )

            time.sleep(
                10
            )

        # API checks every 5 seconds.
        # Candle/trading timeframe remains 1 MINUTE.
        time.sleep(
            POLL_SECONDS
        )


# ============================================================
# SIGNAL HANDLER
# ============================================================

def stop_handler(
    signum,
    frame
):

    global STOP

    STOP = True

    log(
        "BOT STOP SIGNAL RECEIVED"
    )

    record(
        "BOT_STOPPED",
        symbol=SYMBOL,
        runner_ip=RUNNER_IP,
        message=f"signal={signum}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    signal.signal(
        signal.SIGINT,
        stop_handler
    )

    signal.signal(
        signal.SIGTERM,
        stop_handler
    )

    try:

        main()

    except Exception as e:

        log("")
        log(
            "=================================================="
        )
        log(
            "FATAL ERROR"
        )
        log(
            "TYPE:",
            type(e).__name__
        )
        log(
            "ERROR:",
            str(e)
        )
        log(
            "=================================================="
        )

        record(
            "FATAL_ERROR",
            symbol=SYMBOL,
            runner_ip=RUNNER_IP,
            message=(
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

        raise

from __future__ import annotations

import numpy as np
import pandas as pd


def raw_wind_like_inputs(start_date: str = "2024-01-01", end_date: str = "2024-03-31") -> dict[str, pd.DataFrame]:
    etf_flow = daily_ohlcv(["510300.SH", "510500.SH"], start_date, end_date)
    etf_flow = etf_flow.assign(margin_balance=etf_flow["amount"] * 1.2)
    return {
        "index_ohlcv": daily_ohlcv(["000300.SH"], start_date, end_date),
        "futures_ohlcv": daily_ohlcv(["IF.CFE"], start_date, end_date),
        "open_interest": futures_open_interest(["IF.CFE"], start_date, end_date),
        "rates": interest_rates(["DR007.IB", "CGB10Y.IB"], start_date, end_date),
        "etf_flow": etf_flow,
        "overseas_ohlcv": daily_ohlcv(["SPX.GI", "HSI.HI"], start_date, end_date),
        "ashare_ohlcv": daily_ohlcv(["000300.SH", "000905.SH", "000852.SH"], start_date, end_date),
    }


def daily_ohlcv(symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.bdate_range(start_date, end_date)
    for symbol in symbols:
        base = 80.0 + _symbol_seed(symbol) % 60
        for index, date in enumerate(dates):
            close = base + index * 0.04 + np.sin(index / 5.0 + _symbol_seed(symbol) % 3) * 1.2
            open_price = close * 0.998
            rows.append(
                {
                    "date": date.normalize(),
                    "symbol": symbol,
                    "open": round(open_price, 4),
                    "high": round(max(open_price, close) * 1.004, 4),
                    "low": round(min(open_price, close) * 0.996, 4),
                    "close": round(close, 4),
                    "volume": 1_000_000 + index * 2_500,
                    "amount": round(close * (1_000_000 + index * 2_500), 2),
                    "asof_time": "16:30:00",
                    "source": "wind_fixture",
                }
            )
    return pd.DataFrame(rows)


def futures_open_interest(symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.bdate_range(start_date, end_date)
    for symbol in symbols:
        base = 120_000 + _symbol_seed(symbol) % 20_000
        for index, date in enumerate(dates):
            rows.append(
                {
                    "date": date.normalize(),
                    "symbol": symbol,
                    "open_interest": base + index * 100,
                    "volume": 40_000 + index * 120,
                    "asof_time": "16:30:00",
                    "source": "wind_fixture",
                }
            )
    return pd.DataFrame(rows)


def interest_rates(series: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.bdate_range(start_date, end_date)
    for name in series:
        base = 2.0 + (_symbol_seed(name) % 30) / 100.0
        for index, date in enumerate(dates):
            rows.append(
                {
                    "date": date.normalize(),
                    "series": name,
                    "rate": round(base + np.sin(index / 8.0) * 0.02, 4),
                    "asof_time": "16:30:00",
                    "source": "wind_fixture",
                }
            )
    return pd.DataFrame(rows)


def option_chain_fixture(trade_date: str = "2026-06-07", product_group: str = "CSI300") -> pd.DataFrame:
    trade_ts = pd.Timestamp(trade_date).normalize()
    expiry = trade_ts + pd.Timedelta(days=35)
    rows = []
    for strike in [3600.0, 3800.0, 4000.0]:
        for option_type in ["call", "put"]:
            rows.append(
                {
                    "trade_date": trade_ts,
                    "option_code": f"{product_group}_{option_type}_{int(strike)}",
                    "product_group": product_group,
                    "venue": "CFFEX",
                    "underlying_code": "000300.SH",
                    "reference_index_code": "000300.SH",
                    "option_type": option_type,
                    "strike": strike,
                    "expiry_date": expiry,
                    "dte_calendar": 35,
                    "dte_trading": 25,
                    "year_fraction": 35 / 365,
                    "multiplier_or_contract_unit": 100.0,
                    "settlement_type": "cash",
                    "option_style": "European",
                    "adjusted_contract_flag": False,
                    "open": 80.0,
                    "high": 85.0,
                    "low": 75.0,
                    "close": 80.0,
                    "settle": 80.0,
                    "volume": 100,
                    "open_interest": 1000 + int(abs(strike - 3800)),
                    "bid": 79.0,
                    "ask": 81.0,
                    "mid": 80.0,
                    "underlying_price": 3800.0,
                    "reference_index_level": 3800.0,
                    "risk_free_rate": 0.02,
                    "dividend_yield": 0.0,
                    "implied_vol": 0.22,
                    "implied_vol_source": "wind_fixture",
                    "asof_time": "16:30:00",
                    "source": "wind_fixture",
                }
            )
    return pd.DataFrame(rows)


def _symbol_seed(symbol: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(symbol))

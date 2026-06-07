from daily_bias_engine.pipeline import default_history_range


def test_default_history_range_uses_latest_weekday_for_three_year_snapshot() -> None:
    start_date, end_date = default_history_range(years=3, end_date="2026-06-07")

    assert start_date == "2023-06-05"
    assert end_date == "2026-06-05"

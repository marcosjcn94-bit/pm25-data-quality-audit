import math
from datetime import date, timedelta

import pandas as pd
import pytest

from audit import canonicalize, compare, pandas_analysis, read_daily, run, sqlite_analysis


def rows_for(site, poc, start, count, mean, hours=24):
    return [
        (site, poc, (start + timedelta(days=day)).isoformat(), mean, hours)
        for day in range(count)
    ]


def analyze(rows):
    result = canonicalize(pandas_analysis(rows))
    compare(result, canonicalize(sqlite_analysis(rows)))
    return result


def test_leap_year_missing_month_and_unequal_weights():
    start = date(2024, 2, 1)
    rows = (
        rows_for("1103", "3", start, 22, 10.0, 18)
        + rows_for("1302", "3", start, 26, 30.0)
        + rows_for("4009", "3", start, 27, 50.0)
        + rows_for("1103", "3", date(2024, 2, 29), 1, 1000.0, 17)
        + rows_for("9035", "1", date(2024, 2, 29), 1, None)
    )
    monitor, monthly, audit = analyze(rows)
    assert (len(monitor), len(monthly), len(audit)) == (48, 36, 108)
    feb = monitor.query("month == '2024-02'").set_index("site")
    assert feb.calendar_days.tolist() == [29, 29, 29, 29]
    assert feb.valid_days.tolist() == [22, 26, 27, 0]
    assert feb.source_days.tolist() == [23, 26, 27, 1]
    assert feb.eligible_75.tolist() == [1, 1, 1, 0]
    assert feb.eligible_90.tolist() == [0, 0, 1, 0]
    assert feb.loc["1103", "monitor_mean"] == 10
    assert pd.isna(feb.loc["9035", "monitor_mean"])
    selected = monthly.query("month == '2024-02'").set_index("rule")
    all_days = (22 * 10 + 26 * 30 + 27 * 50) / 75
    assert selected.loc["any", "eligible_ids"] == "1103/3;1302/3;4009/3"
    assert selected.loc["any", "equal_monitor_mean"] == 30
    assert selected.loc["any", "equal_day_mean"] == pytest.approx(all_days)
    assert selected.loc["90", "equal_day_mean"] == 50
    assert selected.loc["90", "eligible_ids"] == "4009/3"
    gaps = audit.query("month == '2024-02'").set_index(["contrast", "weight"])
    assert gaps.loc[("weights_any", "equal_monitor_minus_equal_day"), "difference"] == pytest.approx(30 - all_days)
    assert gaps.loc[("90_minus_any", "equal_monitor"), "difference"] == 20
    assert gaps.loc[("90_minus_any", "equal_day"), "difference"] == pytest.approx(50 - all_days)
    missing = monthly.query("month == '2024-01'")
    assert missing.eligible_count.tolist() == [0, 0, 0]
    assert missing.eligible_ids.tolist() == ["", "", ""]
    assert missing.equal_day_mean.isna().all()
    assert missing.equal_monitor_mean.isna().all()


def test_coverage_includes_exact_threshold_and_excludes_one_day_less():
    start = date(2024, 4, 1)
    rows = (rows_for("1103", "3", start, 27, 3.0)
            + rows_for("1302", "3", start, 26, 4.0)
            + rows_for("4009", "3", start, 23, 4.0)
            + rows_for("9035", "1", start, 22, 4.0))
    monitor, _, _ = analyze(rows)
    april = monitor.query("month == '2024-04'").set_index("site")
    assert april.loc["1103", "coverage"] == 0.90
    assert april.loc["1103", "eligible_90"] == 1
    assert april.loc["1302", "eligible_90"] == 0
    assert april.loc["4009", "eligible_75"] == 1
    assert april.loc["9035", "eligible_75"] == 0


def test_duplicate_keys_are_rejected(tmp_path):
    input_path = tmp_path / "daily.csv"
    input_path.write_text(
        "site,poc,date,mean,hours\n1103,3,2024-01-13,2.3,20\n1103,3,2024-01-13,2.3,20\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate monitor-day"):
        read_daily(input_path)


def test_nonfinite_concentration_and_missing_hours_are_invalid(tmp_path):
    input_path = tmp_path / "daily.csv"
    input_path.write_text(
        "site,poc,date,mean,hours\n1103,3,2024-01-13,inf,24\n1103,3,2024-01-14,-3.0,\n",
        encoding="utf-8",
    )
    rows = read_daily(input_path)
    assert rows[0][3] is None and rows[1][4] is None
    monitor, _, _ = analyze(rows)
    jan = monitor.query("month == '2024-01' and site == '1103'").iloc[0]
    assert jan.source_days == 2 and jan.valid_days == 0
    assert math.isnan(jan.monitor_mean)


def test_empty_input_and_cli_outputs(tmp_path):
    input_path = tmp_path / "daily.csv"
    input_path.write_text("site,poc,date,mean,hours\n", encoding="utf-8")
    output = tmp_path / "tables"
    run(input_path, output)
    assert sorted(p.name for p in output.iterdir()) == ["audit.csv", "monitor_months.csv", "monthly.csv"]
    note = output / "notes.md"
    note.write_text("keep me", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    run(input_path, output)
    after = {path.name: path.read_bytes() for path in output.iterdir()}
    assert after == before

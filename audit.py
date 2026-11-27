"""Coverage and weighting audit of EPA AirData PM2.5 monitor-days."""

import argparse
import csv
import math
import sqlite3
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

MONITORS = (("1103", "3"), ("1302", "3"), ("4009", "3"), ("9035", "1"))
RULES = ("any", "75", "90")
FIELDS = ("site", "poc", "date", "mean", "hours")
MONTHS = pd.period_range("2024-01", "2024-12", freq="M")
TABLES = ("monitor_months", "monthly", "audit")
NUMERIC = {
    "monitor_months": {"coverage", "monitor_mean"},
    "monthly": {"equal_monitor_mean", "equal_day_mean", "difference"},
    "audit": {"baseline", "comparison", "difference"},
}
MONTH_COLUMNS = [
    "site", "poc", "month", "calendar_days", "source_days", "valid_days",
    "coverage", "monitor_mean", "eligible_any", "eligible_75", "eligible_90",
]
MONTHLY_COLUMNS = [
    "month", "rule", "eligible_count", "eligible_ids", "valid_monitor_days",
    "equal_monitor_mean", "equal_day_mean", "difference",
]
AUDIT_COLUMNS = ["month", "contrast", "weight", "baseline", "comparison", "difference"]
KEYS = (["site", "poc", "month"], ["month", "rule"], ["month", "contrast", "weight"])


def read_daily(path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or set(reader.fieldnames) != set(FIELDS):
            raise ValueError(f"Expected input columns {', '.join(FIELDS)}")
        rows = []
        keys = set()
        for line, row in enumerate(reader, start=2):
            try:
                site, poc, day, mean_text, hours_text = (row[name] for name in FIELDS)
                if (site, poc) not in MONITORS:
                    raise ValueError(f"unexpected monitor {site}/{poc}")
                parsed = date.fromisoformat(day)
                if parsed.year != 2024 or parsed.isoformat() != day:
                    raise ValueError(f"unexpected date {day!r}")
                key = (site, poc, day)
                if key in keys:
                    raise ValueError(f"duplicate monitor-day {site}/{poc} {day}")
                keys.add(key)
                mean = float(mean_text) if mean_text.strip() else None
                if mean is not None and not math.isfinite(mean):
                    mean = None
                hours = int(hours_text) if hours_text.strip() else None
                if hours is not None and hours < 0:
                    raise ValueError("hours must be nonnegative")
            except (ValueError, AttributeError, TypeError) as error:
                raise ValueError(f"Invalid input line {line}. {error}") from error
            rows.append((*key, mean, hours))
    return rows


def monitor_months(rows):
    daily = pd.DataFrame(rows, columns=FIELDS)
    daily["month"] = daily["date"].str[:7]
    daily["valid_mean"] = daily["mean"].where(daily["hours"].fillna(0).ge(18))
    observed = daily.groupby(["site", "poc", "month"]).agg(
        source_days=("date", "count"),
        valid_days=("valid_mean", "count"),
        monitor_mean=("valid_mean", "mean"),
        valid_sum=("valid_mean", "sum"),
    )
    grid = pd.MultiIndex.from_tuples(
        [(site, poc, str(month)) for site, poc in MONITORS for month in MONTHS],
        names=["site", "poc", "month"],
    )
    monitor = observed.reindex(grid).reset_index()
    counts = ["source_days", "valid_days"]
    monitor[counts] = monitor[counts].fillna(0).astype(int)
    monitor["calendar_days"] = pd.PeriodIndex(monitor["month"], freq="M").days_in_month
    monitor["coverage"] = monitor["valid_days"] / monitor["calendar_days"]
    monitor["eligible_any"] = monitor["valid_days"].ge(1).astype(int)
    monitor["eligible_75"] = monitor["coverage"].ge(0.75).astype(int)
    monitor["eligible_90"] = monitor["coverage"].ge(0.90).astype(int)
    return monitor


def county_months(monitor):
    rows = []
    for month, group in monitor.groupby("month"):
        for rule in RULES:
            included = group.loc[group[f"eligible_{rule}"].eq(1)]
            count = int(included["valid_days"].sum())
            equal_monitor = included["monitor_mean"].mean()
            equal_day = included["valid_sum"].sum() / count if count else math.nan
            rows.append((
                month, rule, len(included), ";".join(included["site"] + "/" + included["poc"]),
                count, equal_monitor, equal_day, equal_monitor - equal_day,
            ))
    return pd.DataFrame(rows, columns=MONTHLY_COLUMNS)


def audit_contrasts(monthly):
    rows = []
    for month, group in monthly.groupby("month"):
        group = group.set_index("rule")
        for rule in RULES:
            row = group.loc[rule]
            rows.append((month, f"weights_{rule}", "equal_monitor_minus_equal_day",
                         row.equal_day_mean, row.equal_monitor_mean, row.difference))
        for first, second in (("any", "75"), ("any", "90"), ("75", "90")):
            for weight in ("equal_monitor", "equal_day"):
                old, new = group.loc[[first, second], f"{weight}_mean"]
                rows.append((month, f"{second}_minus_{first}", weight, old, new, new - old))
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def pandas_analysis(rows):
    monitor = monitor_months(rows)
    monthly = county_months(monitor)
    return monitor[MONTH_COLUMNS], monthly, audit_contrasts(monthly)


def sqlite_analysis(rows):
    sql_path = Path(__file__).with_name("reference.sql")
    db = sqlite3.connect(":memory:")
    try:
        db.execute(
            "CREATE TABLE daily (site TEXT, poc TEXT, date TEXT, mean REAL, hours INTEGER, "
            "PRIMARY KEY (site, poc, date))"
        )
        db.executemany("INSERT INTO daily VALUES (?, ?, ?, ?, ?)", rows)
        db.executescript(sql_path.read_text(encoding="utf-8"))
        return tuple(
            pd.read_sql_query(f"SELECT {', '.join(columns)} FROM reference_{name}", db)
            for name, columns in zip(TABLES, (MONTH_COLUMNS, MONTHLY_COLUMNS, AUDIT_COLUMNS), strict=True)
        )
    finally:
        db.close()


def canonicalize(tables):
    return tuple(
        table.sort_values(key).reset_index(drop=True)
        for table, key in zip(tables, KEYS, strict=True)
    )


def compare(pandas_tables, sqlite_tables):
    for name, actual, expected in zip(TABLES, pandas_tables, sqlite_tables, strict=True):
        if actual.shape != expected.shape or list(actual.columns) != list(expected.columns):
            raise ValueError(f"SQLite disagrees on the shape or columns of {name}")
        for column in actual.columns:
            pd.testing.assert_series_equal(actual[column].isna(), expected[column].isna())
            if column in NUMERIC[name]:
                pd.testing.assert_series_equal(
                    actual[column].astype(float), expected[column].astype(float),
                    check_exact=False, atol=1e-9, rtol=0,
                )
            else:
                pd.testing.assert_series_equal(actual[column], expected[column], check_exact=True)


def run(input_path, output):
    rows = read_daily(input_path)
    pandas_tables = canonicalize(pandas_analysis(rows))
    sqlite_tables = canonicalize(sqlite_analysis(rows))
    compare(pandas_tables, sqlite_tables)
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output) as staging:
        stage = Path(staging)
        for name, table in zip(TABLES, pandas_tables, strict=True):
            table.to_csv(stage / f"{name}.csv", index=False, lineterminator="\n", float_format="%.15g")
        for name in TABLES:
            filename = f"{name}.csv"
            (stage / filename).replace(output / filename)
    print(f"{len(rows):,} monitor-days. Pandas and SQLite agree on 3 result tables.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/daily.csv"))
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()
    try:
        run(args.input, args.output)
    except (ValueError, OSError, AssertionError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

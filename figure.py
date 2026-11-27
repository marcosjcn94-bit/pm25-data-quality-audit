"""Plot both estimands directly from the validated monthly table."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot(path=Path("results/monthly.csv")):
    rows = pd.read_csv(path)
    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True, layout="constrained")
    for rule, label, marker in (("any", "Any valid day", "o"), ("75", "≥75% coverage", "s"),
                                ("90", "≥90% coverage", "^")):
        group = rows.loc[rows.rule == rule].sort_values("month")
        months = pd.to_datetime(group.month).dt.month
        for axis, column in zip(axes, ("equal_monitor_mean", "difference"), strict=True):
            axis.plot(months, group[column], marker=marker, label=label, linewidth=1.4,
                      markersize=4, alpha=0.85)
    axes[0].set(ylabel="PM2.5 (µg/m³)", title="Mean with equal weight per eligible monitor")
    axes[1].axhline(0, color="gray", linewidth=0.8)
    axes[1].set(ylabel="Difference (µg/m³)", xlabel="Month of 2024",
                title="Equal-monitor mean minus pooled monitor-day mean", xticks=range(1, 13))
    axes[0].legend(frameon=False, ncol=3)
    for axis in axes:
        axis.grid(axis="y", alpha=0.2)
    return fig


if __name__ == "__main__":
    plot().savefig("results/coverage.png", dpi=160)

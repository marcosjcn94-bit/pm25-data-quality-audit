"""Rebuild the frozen research input from an original EPA download."""
import argparse
import csv
import hashlib
import io
from pathlib import Path
from zipfile import ZipFile

SOURCE_HASH = "409c2d884935bd0a4099d640b7c526ecb0af1d3aac049697e34c2f9f69dbe91d"
FILTER = {"State Code": "06", "County Code": "037", "Parameter Code": "88101",
          "Sample Duration": "1 HOUR", "Pollutant Standard": "", "Event Type": "None",
          "Units of Measure": "Micrograms/cubic meter (LC)"}
MONITORS = {("1103", "3"), ("1302", "3"), ("4009", "3"), ("9035", "1")}

def extract(archive, output):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_HASH:
        raise ValueError("EPA archive differs from frozen input; obtain the recorded revision.")
    rows = []
    with ZipFile(archive) as z, z.open("daily_88101_2024.csv") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
        for record in reader:
            if all(record[key] == value for key, value in FILTER.items()):
                monitor = record["Site Num"], record["POC"]
                if monitor in MONITORS:
                    rows.append((*monitor, record["Date Local"], record["Arithmetic Mean"],
                                 record["Observation Count"]))
    if len(rows) != 1424:
        raise ValueError(f"Unexpected input size: {len(rows)}")
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(("site", "poc", "date", "mean", "hours"))
        writer.writerows(sorted(rows))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/daily.csv"))
    args = parser.parse_args()
    extract(args.archive, args.output)

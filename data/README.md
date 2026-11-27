# Source and scope

US Environmental Protection Agency, Air Quality System (EPA AirData), daily summaries for parameter 88101, 2024. Retrieved 2026-11-27 from https://aqs.epa.gov/aqsweb/airdata/daily_88101_2024.zip . Original ZIP SHA-256: `409c2d884935bd0a4099d640b7c526ecb0af1d3aac049697e34c2f9f69dbe91d`. See the [EPA file documentation](https://aqs.epa.gov/aqsweb/airdata/FileFormats.html) for definitions. The MIT license covers the original software and accompanying original documentation. Measurements originate from the EPA archive.

The columns site, poc, date, mean and hours retain the source values of Site Num, POC, Date Local, Arithmetic Mean and Observation Count. State, county, parameter, units, standard, event status and sample duration are fixed in the protocol. Each row is a daily summary of hourly samples. Archive revisions are possible. The committed extract is the authoritative input for v1.0.0.

To rebuild, download the ZIP from the link above and run `python extract.py daily_88101_2024.zip --output /tmp/pm25-daily.csv`. Compare against the committed file with `cmp /tmp/pm25-daily.csv data/daily.csv`. A revised ZIP fails the checksum check before any output is written.

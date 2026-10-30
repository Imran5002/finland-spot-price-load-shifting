# Data

## `processed/finland_hourly_spot_prices_2023-01_2026-09.csv`

Cleaned hourly dataset used in every part of the analysis: **32,853 rows**, one per hour, from 1 Jan 2023 02:00 to 30 Sep 2026 23:00 Finnish local time.

### Provenance

| | |
|---|---|
| Compiled source | [vividfog/nordpool-predict-fi](https://github.com/vividfog/nordpool-predict-fi), file [`data/dump.csv`](https://github.com/vividfog/nordpool-predict-fi/blob/main/data/dump.csv) (MIT licence), accessed 5 Oct 2026 |
| Prices | Nord Pool day-ahead, Finland bidding zone, via the Sähkötin API (published incl. VAT) |
| Wind and nuclear power | Fingrid Open Data |
| Temperature | Finnish Meteorological Institute (FMI), station 101786 Oulu Airport |

### Data dictionary

| Column | Type | Description |
|---|---|---|
| `timestamp_utc` | string | Start of the hour in UTC (`YYYY-MM-DD HH:MM`) |
| `local_datetime` | string | Start of the hour in Finnish local time (Europe/Helsinki, DST-aware) |
| `date` | date | Local calendar date |
| `year`, `month`, `hour` | int | Local year, month (1–12) and hour of day (0–23) |
| `weekday` | int | Day of week, 1 = Monday … 7 = Sunday |
| `price_incl_vat_c_per_kwh` | float | Spot price as published, cents/kWh including VAT |
| `vat_rate` | float | VAT rate in force: 0.10 (to 30 Apr 2023), 0.24 (to 31 Aug 2024), 0.255 (from 1 Sep 2024) |
| `price_excl_vat_c_per_kwh` | float | **Analysis price**: `price_incl_vat / (1 + vat_rate)`, cents/kWh |
| `price_eur_per_mwh` | float | Same price in €/MWh (1 c/kWh = 10 €/MWh) |
| `market_error_hour` | bool | `True` for the 10 hours of the 24 Nov 2023 bidding error (−500 €/MWh); excluded from price statistics |
| `wind_mw` | float | Finnish wind power output, MW (negative readings set to 0) |
| `wind_capacity_mw` | float | Installed wind capacity, MW — stops updating after Dec 2024 in the source; **not used** |
| `nuclear_mw` | float | Finnish nuclear power output, MW |
| `oulu_temp_c` | float | Air temperature at Oulu Airport, °C (5 missing hours linearly interpolated) |
| `season` | string | Winter (Dec–Feb), Spring (Mar–May), Summer (Jun–Aug), Autumn (Sep–Nov) |

### Cleaning steps

1. Removed 170 forecast rows without an actual price.
2. Removed the incomplete October 2026 (361 rows) to keep 45 complete months.
3. Checked for duplicate timestamps and missing hours — none found.
4. Converted UTC to Finnish local time.
5. Removed VAT using the official rate for each period (the rate changed twice).
6. Flagged the 10 hours affected by the 24 Nov 2023 trading error (−500 €/MWh).
7. Set 44 negative wind readings to 0 MW.
8. Interpolated 5 missing Oulu temperature hours.

### Notes

- Since 1 Oct 2025 the market settles in 15-minute intervals; the source averages these to hourly values.
- The first day (1 Jan 2023) starts at 02:00 local time and therefore has 22 hours.
- Days with a DST change have 23 or 25 hours.

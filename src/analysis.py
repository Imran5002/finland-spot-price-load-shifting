"""
Turning Price Swings into Savings — reproducible analysis
=========================================================

Recomputes the key figures of the report from the cleaned hourly dataset
(data/processed/finland_hourly_spot_prices_2023-01_2026-09.csv):

  1. Price level and daily price swing per period        (Section 4.2, Table 1)
  2. Average price by hour of day and season             (Section 4.3, Figure 2)
  3. Price drivers: wind output and Oulu temperature     (Section 4.3, Figure 3)
  4. Modelled household savings and market value pool    (Section 4.4, Figure 4)
  5. Share of days a fixed night timer misses cheap hours (Section 4.3, Figure 5)

All prices are in cents per kWh EXCLUDING VAT; household savings are in EUR
INCLUDING today's 25.5 % VAT so that all years are comparable.

Usage
-----
    python src/analysis.py            # prints a summary and writes results/*.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "finland_hourly_spot_prices_2023-01_2026-09.csv"
RESULTS = ROOT / "results"

# ---------------------------------------------------------------------------
# Assumptions (mirrors the 'Assumptions' sheet of the Excel workbook)
# ---------------------------------------------------------------------------
EV_KWH_PER_DAY = 7.5            # ≈13,800 km/yr × ~0.2 kWh/km (Statistics Finland)
WATER_HEATER_KWH_PER_DAY = 8.0  # 300-litre storage heater ≈ 2,900 kWh/yr
VAT = 0.255                     # Finnish VAT on electricity since 1 Sep 2024
BATTERY_KWH = 10.0              # comparison case: one full cycle per day
BATTERY_EFFICIENCY = 0.90       # round-trip efficiency
EV_STOCK_FINLAND = 169_458      # fully electric cars, end of 2025
SPOT_CONTRACT_SHARE = 0.33      # share of contracts tied to the spot price

EV_HOURS = 3                    # 3.7 kW home charger
EV_BASELINE_HOURS = range(17, 20)       # charge on arrival, 17:00–19:59
EV_SMART_WINDOW = (17, 7)               # cheapest 3 h between 17:00 and 06:59 next day
WH_HOURS = 4
WH_BASELINE_HOURS = [22, 23, 0, 1, 2, 3, 4, 5, 6]  # fixed 22:00–06:59 night timer
NIGHT_WINDOW = set(WH_BASELINE_HOURS)

PERIODS = {
    "2023": ("2023-01-01", "2023-12-31"),
    "2024": ("2024-01-01", "2024-12-31"),
    "2025": ("2025-01-01", "2025-12-31"),
    "2026 (Jan–Sep)": ("2026-01-01", "2026-09-30"),
    "Last 12 months": ("2025-10-01", "2026-09-30"),
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_hourly(path: Path = DATA) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["local_datetime", "date"])
    df["price"] = df["price_excl_vat_c_per_kwh"]
    return df


def valid(df: pd.DataFrame) -> pd.DataFrame:
    """Hours used for price statistics (drops the 10 bidding-error hours)."""
    return df[~df["market_error_hour"]]


# ---------------------------------------------------------------------------
# Daily metrics
# ---------------------------------------------------------------------------
def daily_metrics(df: pd.DataFrame) -> pd.DataFrame:
    v = valid(df)
    g = v.groupby("date")["price"]

    daily = pd.DataFrame({
        "avg_price": g.mean(),
        "min_hour": g.min(),
        "max_hour": g.max(),
        "avg_4_cheapest": g.apply(lambda x: x.nsmallest(4).mean()),
        "avg_3_cheapest": g.apply(lambda x: x.nsmallest(3).mean()),
        "avg_3_dearest": g.apply(lambda x: x.nlargest(3).mean()),
        "negative_hours": g.apply(lambda x: int((x < 0).sum())),
    })
    daily["daily_swing"] = daily["max_hour"] - daily["min_hour"]
    daily["saving_per_kwh_shifted"] = daily["avg_price"] - daily["avg_4_cheapest"]

    # --- EV charging: arrival baseline vs cheapest 3 h overnight -------------
    # Days that contain bidding-error hours are left out of the EV comparison.
    error_days = set(df.loc[df["market_error_hour"], "date"])
    ev_base = v[v["hour"].isin(EV_BASELINE_HOURS)].groupby("date")["price"].mean()

    start, end = EV_SMART_WINDOW
    w = v[(v["hour"] >= start) | (v["hour"] < end)].copy()
    w["anchor"] = np.where(w["hour"] >= start, w["date"], w["date"] - pd.Timedelta(days=1))
    ev_smart = w.groupby("anchor")["price"].apply(lambda x: x.nsmallest(EV_HOURS).mean())
    last_day = df["date"].max()  # its overnight window runs into missing data

    daily["ev_baseline"] = ev_base
    daily["ev_smart"] = ev_smart
    daily.loc[daily.index.isin(error_days) | (daily.index == last_day),
              ["ev_baseline", "ev_smart"]] = np.nan
    daily["ev_saving_eur"] = ((daily["ev_baseline"] - daily["ev_smart"])
                              * EV_KWH_PER_DAY * (1 + VAT) / 100).fillna(0)

    # --- Water heater: fixed night timer vs cheapest 4 h of the day ----------
    daily["wh_baseline"] = (v[v["hour"].isin(WH_BASELINE_HOURS)]
                            .groupby("date")["price"].mean())
    daily["wh_smart"] = daily["avg_4_cheapest"]
    daily["wh_saving_eur"] = ((daily["wh_baseline"] - daily["wh_smart"])
                              * WATER_HEATER_KWH_PER_DAY * (1 + VAT) / 100)

    daily["household_saving_eur"] = daily["ev_saving_eur"] + daily["wh_saving_eur"]

    # --- Home battery comparison (one cycle per day) -------------------------
    daily["battery_value_eur"] = (np.maximum(
        0, BATTERY_KWH * BATTERY_EFFICIENCY * daily["avg_3_dearest"]
        - BATTERY_KWH * daily["avg_3_cheapest"]) * (1 + VAT) / 100)

    # --- Does a fixed 22–07 timer miss any of the 4 cheapest hours? ----------
    cheapest4 = v.loc[v.groupby("date")["price"].nsmallest(4).index.get_level_values(1)]
    daily["cheap_hour_outside_night"] = (
        cheapest4.groupby("date")["hour"].apply(lambda hrs: int(any(h not in NIGHT_WINDOW for h in hrs))))

    # --- Weather and wind context ---------------------------------------------
    daily["avg_wind_gw"] = df.groupby("date")["wind_mw"].mean() / 1000
    daily["oulu_temp_c"] = df.groupby("date")["oulu_temp_c"].mean()
    return daily


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def period_summary(df: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    v = valid(df)
    rows = []
    for name, (start, end) in PERIODS.items():
        hv = v[(v["date"] >= start) & (v["date"] <= end)]
        dv = daily.loc[start:end]
        rows.append({
            "period": name,
            "hours": len(hv),
            "avg_price_c_kwh": hv["price"].mean(),
            "avg_daily_swing_c_kwh": dv["daily_swing"].mean(),
            "share_days_swing_over_10c": (dv["daily_swing"] > 10).mean(),
            "negative_price_hours": int((hv["price"] < 0).sum()),
            "spike_hours_over_20c": int((hv["price"] > 20).sum()),
            "saving_per_kwh_shifted_c": dv["saving_per_kwh_shifted"].mean(),
            "ev_saving_eur": dv["ev_saving_eur"].sum(),
            "water_heater_saving_eur": dv["wh_saving_eur"].sum(),
            "household_saving_eur": dv["household_saving_eur"].sum(),
            "battery_value_eur": dv["battery_value_eur"].sum(),
            "share_days_cheap_hour_outside_night": dv["cheap_hour_outside_night"].mean(),
        })
    return pd.DataFrame(rows).set_index("period")


def hour_by_season(df: pd.DataFrame) -> pd.DataFrame:
    v = valid(df)
    table = v.pivot_table(index="hour", columns="season", values="price", aggfunc="mean")
    return table[["Winter", "Spring", "Summer", "Autumn"]]


def wind_bands(df: pd.DataFrame) -> pd.DataFrame:
    v = valid(df)
    edges = [-np.inf, 1000, 2000, 3000, 4000, 5000, 6000, np.inf]   # right-closed bands
    labels = ["0–1", "1–2", "2–3", "3–4", "4–5", "5–6", "6+"]
    band = pd.cut(v["wind_mw"], bins=edges, labels=labels, right=True)
    out = v.groupby(band, observed=True)["price"].agg(avg_price_c_kwh="mean", hours="size")
    out["share_negative"] = v.groupby(band, observed=True)["price"].apply(lambda x: (x < 0).mean())
    out.index.name = "wind_output_gw"
    return out


def temperature_bands(daily: pd.DataFrame) -> pd.DataFrame:
    edges = [-np.inf, -20, -10, 0, 10, 20, np.inf]
    labels = ["< −20", "−20…−10", "−10…0", "0…10", "10…20", "> 20"]
    band = pd.cut(daily["oulu_temp_c"], bins=edges, labels=labels, right=True)
    out = daily.groupby(band, observed=True)["daily_swing"].agg(avg_daily_swing_c_kwh="mean", days="size")
    out.index.name = "oulu_daily_mean_temp_c"
    return out


def market_value_pool(summary: pd.DataFrame, period: str = "Last 12 months") -> dict:
    ev_saving = summary.loc[period, "ev_saving_eur"]
    spot_evs = EV_STOCK_FINLAND * SPOT_CONTRACT_SHARE
    return {
        "ev_owners_on_spot": spot_evs,
        "ev_saving_per_owner_eur": ev_saving,
        "value_pool_spot_owners_eur": spot_evs * ev_saving,
        "value_pool_all_owners_eur": EV_STOCK_FINLAND * ev_saving,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    df = load_hourly()
    daily = daily_metrics(df)
    summary = period_summary(df, daily)
    hours = hour_by_season(df)
    wind = wind_bands(df)
    temp = temperature_bands(daily)
    pool = market_value_pool(summary)

    v = valid(df)
    # Correlations follow the workbook's 'Drivers' sheet (computed over all hours).
    r_wind = df["wind_mw"].corr(df["price"])
    r_temp = df["oulu_temp_c"].corr(df["price"])

    daily.to_csv(RESULTS / "daily_metrics.csv", float_format="%.4f")
    summary.to_csv(RESULTS / "period_summary.csv", float_format="%.4f")
    hours.to_csv(RESULTS / "price_by_hour_and_season.csv", float_format="%.3f")
    wind.to_csv(RESULTS / "price_by_wind_band.csv", float_format="%.4f")
    temp.to_csv(RESULTS / "swing_by_temperature_band.csv", float_format="%.3f")

    pd.set_option("display.width", 140)
    print(f"Hourly records: {len(df):,}  (valid for price statistics: {len(v):,})")
    print(f"Days: {len(daily):,}   Period: {df['date'].min():%d %b %Y} – {df['date'].max():%d %b %Y}\n")

    t1 = summary[["avg_price_c_kwh", "avg_daily_swing_c_kwh", "negative_price_hours",
                  "saving_per_kwh_shifted_c", "ev_saving_eur", "water_heater_saving_eur",
                  "household_saving_eur", "share_days_cheap_hour_outside_night"]].copy()
    print("Key metrics by period (Table 1 / Figures 4–5)")
    print(t1.round(2).to_string(), "\n")

    print("Average price by hour and season, c/kWh (Figure 2)")
    print(hours.round(1).T.to_string(), "\n")

    print("Average price by wind output (Figure 3, left)")
    print(wind.round(2).to_string())
    print(f"Correlation, hourly price vs wind output     : r = {r_wind:.2f}")
    print(f"Correlation, hourly price vs Oulu temperature: r = {r_temp:.2f}\n")

    print("Average daily swing by Oulu temperature (Figure 3, right)")
    print(temp.round(1).to_string(), "\n")

    print("Indicative value pool for smart EV charging (last 12 months)")
    print(f"  EV owners on spot contracts : {pool['ev_owners_on_spot']:,.0f}")
    print(f"  Saving per EV owner         : €{pool['ev_saving_per_owner_eur']:,.0f} / year")
    print(f"  Value pool (spot owners)    : €{pool['value_pool_spot_owners_eur'] / 1e6:,.1f} M / year")
    print(f"  Value pool (all EV owners)  : €{pool['value_pool_all_owners_eur'] / 1e6:,.1f} M / year")
    print(f"\nResult tables written to {RESULTS.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()

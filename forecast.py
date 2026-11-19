import os

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import nbinom

DB_PATH = os.path.join(os.path.dirname(__file__), "music_pipeline.duckdb")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HORIZON = 7
MIN_TRAIN_DAYS = 56  # less than 8 weeks -> level-only model

con = duckdb.connect(DB_PATH)

# date range of the data
min_date, max_date = con.execute("""
    SELECT MIN(played_date), MAX(played_date) FROM stg_scrobbles
""").fetchone()
min_date = pd.Timestamp(min_date).normalize()
max_date = pd.Timestamp(max_date).normalize()

today = pd.Timestamp.now(tz="Europe/Berlin").tz_localize(None).normalize()

if max_date >= today:  # today is incomplete -> train until yesterday
    max_date = today - pd.Timedelta(days=1)

if (today - max_date).days > 2:  # stale data: abort instead of a wrong forecast
    raise RuntimeError(f"Letzter Tag in den Daten: {max_date.date()}, Pipeline prüfen")

first_target = max_date + pd.Timedelta(days=1)

# gapless daily series (days without plays = 0)
daily = con.execute(
    """
    SELECT CAST(played_date AS DATE) AS played_date, COUNT(*) AS play_count
    FROM stg_scrobbles
    WHERE CAST(played_date AS DATE) BETWEEN ? AND ?
    GROUP BY 1
    ORDER BY 1
    """,
    [min_date.date(), max_date.date()],
).fetchdf()

full = pd.date_range(min_date, max_date, freq="D")  # built once, ends at max_date
daily["played_date"] = pd.to_datetime(daily["played_date"])
activity = (
    daily.set_index("played_date")["play_count"]
    .reindex(full, fill_value=0)
    .rename_axis("played_date")
    .reset_index()
)
activity["Day"] = pd.Categorical(activity["played_date"].dt.day_name(), categories=DAYS)

# control
assert activity["played_date"].is_unique
assert activity["played_date"].diff().dropna().eq(pd.Timedelta(days=1)).all()
assert activity["played_date"].max() == max_date

train = activity  # everything up to max_date is training data

# future days
future = pd.DataFrame({"target_date": pd.date_range(first_target, periods=HORIZON)})
future["Day"] = pd.Categorical(future["target_date"].dt.day_name(), categories=DAYS)


# model
def fit_nb(train):
    """Weekday model, falls back to level-only if there is too little data."""
    if len(train) < MIN_TRAIN_DAYS or train["Day"].nunique() != 7:
        model_name = "nb_level"
        formula = "play_count ~ 1"
        start = np.array([np.log(max(train["play_count"].mean(), 0.1)), 0.5])
    else:
        model_name = "nb_weekday"
        formula = "play_count ~ 0 + C(Day)"
        means = train.groupby("Day", observed=True)["play_count"].mean().clip(lower=0.1)
        start = np.append(np.log(means.values), 0.5)  # 7 coefficients + alpha

    m = smf.negativebinomial(formula, data=train).fit(
        start_params=start, method="bfgs", maxiter=1000, disp=0
    )
    if not m.mle_retvals["converged"]:
        raise RuntimeError("NegBin-Fit didn't converge")
    return m, model_name


m, model_name = fit_nb(train)

# "~ 1" can return a single value -> broadcast to the forecast horizon
mu = np.broadcast_to(np.asarray(m.predict(future), dtype=float), (HORIZON,))
alpha = m.params["alpha"]  # dispersion

n = 1 / alpha
p = n / (n + mu)
lo = nbinom.ppf(0.10, n, p)  # 80-%-interval
hi = nbinom.ppf(0.90, n, p)

forecast_daily = pd.DataFrame(
    {
        "run_date": today.date(),
        "train_end": max_date.date(),
        "target_date": future["target_date"].dt.date,
        "mu": mu,
        "lo": lo,
        "hi": hi,
        "alpha": alpha,
        "zero_rate": (train["play_count"] == 0).mean(),
        "n_train": len(train),
        "model": model_name,
    }
)

# write to duckdb
con.execute("""
    CREATE TABLE IF NOT EXISTS forecast_daily (
        run_date DATE, train_end DATE, target_date DATE,
        mu DOUBLE, lo DOUBLE, hi DOUBLE,
        alpha DOUBLE, zero_rate DOUBLE, n_train INTEGER, model VARCHAR
    )
""")
con.execute("ALTER TABLE forecast_daily ADD COLUMN IF NOT EXISTS model VARCHAR")
con.execute("DELETE FROM forecast_daily WHERE run_date = ?", [today.date()])
con.register("fc", forecast_daily)
con.execute("INSERT INTO forecast_daily BY NAME SELECT * FROM fc")
con.close()
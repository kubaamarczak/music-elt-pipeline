import os

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import nbinom

DB_PATH = os.path.join(os.path.dirname(__file__), "music_pipeline.duckdb")

con = duckdb.connect(DB_PATH)

# get activity play count table
min_date, max_date = con.execute("""
    SELECT MIN(played_date), MAX(played_date) FROM stg_scrobbles
""").fetchone()
min_date, max_date = (
    pd.Timestamp(min_date).normalize(),
    pd.Timestamp(max_date).normalize(),
)

today = pd.Timestamp.now(tz="Europe/Berlin").tz_localize(None).normalize()

if max_date >= today:  # today incomplete
    max_date = today - pd.Timedelta(days=1)

if (today - max_date).days > 2:  # old data
    raise RuntimeError(f"Letzter Tag in den Daten: {max_date.date()}, Pipeline prüfen")

full = pd.date_range(min_date, max_date, freq="D")
first_target = max_date + pd.Timedelta(days=1)

activity = con.execute(f"""
    SELECT played_date, COUNT(*) AS play_count, DAYNAME(played_date) AS "Day"
    FROM stg_scrobbles
    WHERE played_date BETWEEN '{min_date}' AND '{max_date}'
    GROUP BY played_date
    ORDER BY played_date
""").fetchdf()

# clean up dates w/o listening
full = pd.date_range(
    activity["played_date"].min(), activity["played_date"].max(), freq="D"
)

activity = (
    activity.set_index("played_date")
    .reindex(full)
    .rename_axis("played_date")
    .reset_index()
)
activity["play_count"] = activity["play_count"].fillna(0)
days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
activity["Day"] = pd.Categorical(activity["played_date"].dt.day_name(), categories=days)

# control
assert activity["played_date"].is_unique
assert activity["played_date"].diff().dropna().eq(pd.Timedelta(days=1)).all()

# weekly mean as base metric
activity["weekly_mean"] = activity.groupby("Day")["play_count"].transform(
    lambda s: s.shift(1).expanding().mean()
)

# model fit
train = activity[activity["played_date"] <= max_date]
future = pd.DataFrame({"target_date": pd.date_range(first_target, periods=7)})
future["Day"] = pd.Categorical(future["target_date"].dt.day_name(), categories=days)

if len(train) < 56 or train["Day"].nunique() != 7:  # less than 8 weeks
    formula = "play_count ~ 1"  # niveau only
else:
    formula = "play_count ~ 0 + C(Day)"

# function for model fitting
def fit_nb_weekday(train):
    means = train.groupby("Day", observed=True)["play_count"].mean().clip(lower=0.1)
    start = np.append(np.log(means.values), 0.5)
    m = smf.negativebinomial(formula, data=train).fit(
        start_params=start, method="bfgs", maxiter=1000, disp=0
    )
    if not m.mle_retvals["converged"]:
        raise RuntimeError("NegBin-Fit didn't converge")
    return m

# predictions
m = fit_nb_weekday(train)
mu = m.predict(future)  # point prediction
alpha = m.params["alpha"]  # dispersion

n = 1 / alpha
p = n / (n + mu)
lo = nbinom.ppf(0.10, n, p)  # 80-%-interval
hi = nbinom.ppf(0.90, n, p)

# append to data frame
forecast_daily = pd.DataFrame(
    {
        "run_date": today.date(),
        "target_date": future["target_date"].dt.date,
        "train_end": max_date.date(),
        "mu": np.asarray(mu),
        "lo": np.asarray(lo),
        "hi": np.asarray(hi),
        "alpha": 1 / n,
        "zero_rate": (train["play_count"] == 0).mean(),
        "n_train": len(train),
    }
)

# create fc table in duckdb
con.execute("""
    CREATE TABLE IF NOT EXISTS forecast_daily (
        run_date DATE, train_end DATE, target_date DATE,
        mu DOUBLE, lo DOUBLE, hi DOUBLE,
        alpha DOUBLE, zero_rate DOUBLE, n_train INTEGER
    )
""")
con.execute("DELETE FROM forecast_daily WHERE run_date = ?", [today.date()])
con.register("fc", forecast_daily)
con.execute("INSERT INTO forecast_daily BY NAME SELECT * FROM fc")
con.close()

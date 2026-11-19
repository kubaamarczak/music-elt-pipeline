import os

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import nbinom
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.stattools import acf

DB_PATH = os.path.join(os.path.dirname(__file__), "music_pipeline.duckdb")

con = duckdb.connect(DB_PATH, read_only=True)

min_date, max_date = con.execute("""
    SELECT MIN(played_date), MAX(played_date) FROM stg_scrobbles
""").fetchone()


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
activity["Day"] = activity["played_date"].dt.day_name()
activity["is_sat"] = (activity["Day"] == "Saturday").astype(int)

# control
assert activity["played_date"].is_unique
assert activity["played_date"].diff().dropna().eq(pd.Timedelta(days=1)).all()
print(len(activity))


# baseline metrics
activity["bl_avg"] = [
    np.mean(activity["play_count"]) for _ in range(len(activity["play_count"]))
]
activity["bl_med"] = [
    np.median(activity["play_count"]) for _ in range(len(activity["play_count"]))
]
activity["bl_pers"] = activity["play_count"].shift(1)
activity["bl_seas_pers"] = activity["play_count"].shift(7)
activity["bl_floating_mean (1 week)"] = (
    activity["play_count"].shift(1).rolling(7).mean()
)
activity["bl_floating_mean (2 weeks)"] = (
    activity["play_count"].shift(1).rolling(14).mean()
)
activity["bl_floating_mean (month)"] = (
    activity["play_count"].shift(1).rolling(28).mean()
)
activity["weekly_mean"] = activity.groupby("Day")["play_count"].transform(
    lambda s: s.shift(1).expanding().mean()
)

# baseline predictive model (holt winters with seasonal effects)
model = ExponentialSmoothing(
    activity["play_count"],
    trend="add",  # 'add', 'mul' or None
    seasonal="add",  # 'add', 'mul' or None
    seasonal_periods=12,  # period length
    damped_trend=True,  # optonal damped trend
)
fitted_model = model.fit(optimized=True)  # automatic parameter optimization
forecast = fitted_model.forecast(steps=7)
# print(forecast)


# print(activity)


# first eval
tscv = TimeSeriesSplit(n_splits=40, test_size=7)

results_hw = []
for i, (train_index, test_index) in enumerate(tscv.split(activity["played_date"])):
    print(f"Fold {i}:")
    # print(f"  Train: index={train_index}")
    # print(f"  Test:  index={test_index}")

    assert activity.iloc[test_index]["Day"].eq("Saturday").sum() == 1

    model = ExponentialSmoothing(
        activity["play_count"].iloc[train_index],
        trend="add",  # 'add', 'mul' or None
        seasonal=None,  # 'add', 'mul' or None
        seasonal_periods=7,  # period length
        damped_trend=None,  # optonal damped trend
    )
    fitted_model = model.fit(optimized=True)  # automatic parameter optimization
    forecast = fitted_model.forecast(steps=7)
    results_hw.append(forecast)

pred_hw = pd.concat(results_hw)

# print(pred_hw)

true_counts = activity["play_count"].loc[pred_hw.index]

preds = {
    "hw": pred_hw,
    "global_mean": activity["bl_avg"],
    "median": activity["bl_med"],
    "seas_naive": activity["bl_seas_pers"],
    "float_1w": activity["bl_floating_mean (1 week)"],
    "float_2w": activity["bl_floating_mean (2 weeks)"],
    "float_month": activity["bl_floating_mean (month)"],
    "weekday_mean": activity["weekly_mean"],
}

# preds: dict Name -> Series (Index = Tagesposition)
common = activity["play_count"].index
for p in preds.values():
    common = common.intersection(p.dropna().index)

for name, p in preds.items():
    y, yhat = activity["play_count"].loc[common], p.loc[common]
    rmse = ((y - yhat) ** 2).mean() ** 0.5
    mae = (y - yhat).abs().mean()
    print(f"{name:20s} RMSE {rmse:6.2f}  MAE {mae:6.2f}  (n={len(common)})")

# print("actual mean/std: ", true_counts.mean(), true_counts.std())

## bootstrap
y = activity["play_count"].loc[common]
e_avg = (y - preds["global_mean"].loc[common]) ** 2
e_wm = (y - preds["weekday_mean"].loc[common]) ** 2

d = (e_avg - e_wm).to_numpy()

rng = np.random.default_rng(42)

boot = np.array([rng.choice(d, size=len(d), replace=True).mean() for _ in range(5000)])

# print("avg difference:", d.mean())
# print("95%-CI:", np.percentile(boot, [2.5, 97.5]))
# print("amount resamples advantage weekly mean:", (boot > 0).mean())


block = 7
n = len(d)
starts_max = n - block + 1


def block_sample():
    k = int(np.ceil(n / block))
    idx = rng.integers(0, starts_max, size=k)
    return np.concatenate([d[s : s + block] for s in idx])[:n]


boot_b = np.array([block_sample().mean() for _ in range(5000)])
# print(np.percentile(boot_b, [2.5, 97.5]))


## bootstrap mae
y = activity["play_count"].loc[common]
e_avg = (y - preds["global_mean"].loc[common]).abs()
e_wm = (y - preds["weekday_mean"].loc[common]).abs()

d = (e_avg - e_wm).to_numpy()

rng = np.random.default_rng(42)

boot = np.array([rng.choice(d, size=len(d), replace=True).mean() for _ in range(5000)])

# print("avg difference:", d.mean())
# print("95%-CI:", np.percentile(boot, [2.5, 97.5]))
# print("amount resamples advantage weekly mean:", (boot > 0).mean())


block = 7
n = len(d)
starts_max = n - block + 1


def block_sample():
    k = int(np.ceil(n / block))
    idx = rng.integers(0, starts_max, size=k)
    return np.concatenate([d[s : s + block] for s in idx])[:n]


boot_b = np.array([block_sample().mean() for _ in range(5000)])
# print(np.percentile(boot_b, [2.5, 97.5]))

# acf
residuals = y - preds["weekday_mean"].loc[common]

vals, confint = acf(residuals, nlags=28, alpha=0.05)
# print(vals[:8].round(3))

plot_acf(residuals, lags=28)
plot_pacf(residuals, lags=28)
# plt.show()

# print(acorr_ljungbox(residuals, lags=[7, 14]))
# plt.show()

activity["is_sat"] = (activity["Day"] == "Saturday").astype(int)

train = activity.iloc[train_index]
test = activity.iloc[test_index]

m = smf.negativebinomial("play_count ~ is_sat", data=train).fit()
mu = m.predict(test)  # Punktprognose
alpha = m.params["alpha"]  # Dispersion

n = 1 / alpha
p = n / (n + mu)
lo = nbinom.ppf(0.10, n, p)  # 80-%-Intervall
hi = nbinom.ppf(0.90, n, p)

# print("n: ", n, "p: ", p, "[", lo, hi, "]")

n_folds, p_folds, lo_folds, hi_folds = [], [], [], []

for i, (train_index, test_index) in enumerate(tscv.split(activity["played_date"])):
    print(f"Fold {i}:")
    # print(f"  Train: index={train_index}")
    # print(f"  Test:  index={test_index}")

    assert activity.iloc[test_index]["Day"].eq("Saturday").sum() == 1

    m = smf.negativebinomial(
        "play_count ~ is_sat", data=activity.iloc[train_index]
    ).fit()
    mu = m.predict(activity.iloc[test_index])  # Punktprognose
    alpha = m.params["alpha"]  # Dispersion

    n = 1 / alpha
    p = n / (n + mu)
    lo = nbinom.ppf(0.10, n, p)  # 80-%-Intervall
    hi = nbinom.ppf(0.90, n, p)
    n_folds.append(n)
    p_folds.append(p)
    lo_folds.append(lo)
    hi_folds.append(hi)

# print(n_folds, "\n", p_folds, "\n", lo_folds, "\n", hi_folds)

lo = np.concatenate(lo_folds)
hi = np.concatenate(hi_folds)
y = activity["play_count"].iloc[common].to_numpy()
sat = activity["is_sat"].iloc[common].to_numpy() == 1

hit = (y >= lo) & (y <= hi)
miss_under, miss_over = (y < lo), (y > hi)
# print(hit.mean(), hit[sat].mean(), hit[~sat].mean())
# print(miss_under.sum(), miss_over.sum())
# print("ohne Nulltage:", (miss_under & (y > 0)).sum(), miss_over.sum())
# print("Sa:", miss_under[sat].sum(), miss_over[sat].sum(), " Nicht-Sa:", miss_under[~sat].sum(), miss_over[~sat].sum())
# print("Sa unter lo:", (y[sat & miss_under]).tolist())
# print("Nulltage gesamt/Sa:", (y == 0).sum(), (y[sat] == 0).sum())
# print("Fehlgriffe auf Nulltagen:", (y[~hit] == 0).sum(), "von", (~hit).sum())


lo_e, hi_e = [], []
for train_index, test_index in tscv.split(activity):
    tr = activity.iloc[train_index]
    q = tr.groupby("is_sat")["play_count"].quantile([0.1, 0.9]).unstack()
    te = activity.iloc[test_index]
    lo_e.append(te["is_sat"].map(q[0.1]).to_numpy())
    hi_e.append(te["is_sat"].map(q[0.9]).to_numpy())
lo_e, hi_e = np.concatenate(lo_e), np.concatenate(hi_e)


def interval_score(y, l, h, a=0.2):
    return (h - l) + (2 / a) * np.maximum(l - y, 0) + (2 / a) * np.maximum(y - h, 0)


for name, l, h in [("NegBin", lo, hi), ("empirisch", lo_e, hi_e)]:
    s = interval_score(y, l, h)
    # print(f"{name:10s} gesamt {s.mean():.1f}  Sa {s[sat].mean():.1f}  Nicht-Sa {s[~sat].mean():.1f}")


s_nb = interval_score(y, lo, hi)
s_em = interval_score(y, lo_e, hi_e)
d = s_nb - s_em  # positiv = empirisch besser


def block_boot(d, block=7, n_boot=5000, seed=42):
    rng = np.random.default_rng(seed)
    n = len(d)
    k = int(np.ceil(n / block))
    out = []
    for _ in range(n_boot):
        starts = rng.integers(0, n - block + 1, size=k)
        out.append(np.concatenate([d[s : s + block] for s in starts])[:n].mean())
    return np.percentile(out, [2.5, 97.5])


# print("gesamt:", d.mean(), block_boot(d))
# print("Sa:    ", d[sat].mean(), np.percentile(
#    [np.random.default_rng(i).choice(d[sat], sat.sum()).mean() for i in range(5000)], [2.5, 97.5]))


# plt.plot(range(280), activity["play_count"].loc[pred_hw.index])

order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# sns.boxplot(data=activity, x="Day", y="play_count", order=order)

# plt.show()


# -- more forecast building --

# saturday arima no AR(p)
start = len(activity) - 280
preds_ar = {}
for t in range(start, len(activity)):
    y_train = activity["play_count"].iloc[:t]
    X_train = activity[["is_sat"]].iloc[:t]
    m = ARIMA(y_train, exog=X_train, order=(0, 0, 0)).fit()
    preds_ar[t] = m.forecast(steps=1, exog=activity[["is_sat"]].iloc[[t]]).iloc[0]
pred_ar = pd.Series(preds_ar)

print(pred_ar)
print(activity.iloc[:t].groupby("is_sat")["play_count"].mean())
print(m.params)

y = activity["play_count"].loc[common]
y_ar = activity["play_count"].loc[pred_ar.index]
e_wm = (y - preds["weekday_mean"].loc[common]).abs()
e_ar = (y_ar - pred_ar).abs()

d = (e_wm - e_ar).to_numpy()

rng = np.random.default_rng(42)

boot = np.array([rng.choice(d, size=len(d), replace=True).mean() for _ in range(5000)])

print("avg difference:", d.mean())
print("95%-CI:", np.percentile(boot, [2.5, 97.5]))
print("amount resamples advantage arima:", (boot > 0).mean())


# saturday arima no AR(p)
start = len(activity) - 280
preds_ar1 = {}
for t in range(start, len(activity)):
    y_train = activity["play_count"].iloc[:t]
    X_train = activity[["is_sat"]].iloc[:t]
    m = ARIMA(y_train, exog=X_train, order=(1, 0, 0)).fit()
    preds_ar1[t] = m.forecast(steps=1, exog=activity[["is_sat"]].iloc[[t]]).iloc[0]
pred_ar1 = pd.Series(preds_ar1)

print(pred_ar1)
print(activity.iloc[:t].groupby("is_sat")["play_count"].mean())
print(m.params)

y_ar1 = activity["play_count"].loc[pred_ar1.index]
e_ar1 = (y_ar1 - pred_ar1).abs()
e_ref = e_ar

d = (e_ref - e_ar1).to_numpy()

rng = np.random.default_rng(42)

boot = np.array([rng.choice(d, size=len(d), replace=True).mean() for _ in range(5000)])

print("avg difference:", d.mean())
print("95%-CI:", np.percentile(boot, [2.5, 97.5]))
print("amount resamples advantage arima:", (boot > 0).mean())


# saturday arima no AR(p)
start = len(activity) - 280
preds_ar2 = {}
for t in range(start, len(activity)):
    y_train = activity["play_count"].iloc[:t]
    X_train = activity[["is_sat"]].iloc[:t]
    m = ARIMA(y_train, exog=X_train, order=(2, 0, 0)).fit()
    preds_ar2[t] = m.forecast(steps=1, exog=activity[["is_sat"]].iloc[[t]]).iloc[0]
pred_ar2 = pd.Series(preds_ar2)

print(pred_ar2)
print(activity.iloc[:t].groupby("is_sat")["play_count"].mean())
print(m.params)

y_ar2 = activity["play_count"].loc[pred_ar2.index]
e_ar2 = (y_ar2 - pred_ar2).abs()
e_ref = e_ar

d = (e_ref - e_ar2).to_numpy()

rng = np.random.default_rng(42)

boot = np.array([rng.choice(d, size=len(d), replace=True).mean() for _ in range(5000)])

print("avg difference:", d.mean())
print("95%-CI:", np.percentile(boot, [2.5, 97.5]))
print("amount resamples advantage arima:", (boot > 0).mean())


# lightgbm model (tree based)
tscv = TimeSeriesSplit(n_splits=280, test_size=1)

y = activity["play_count"]
activity["day_mapped"] = activity["played_date"].dt.isocalendar().day
activity["lag1"] = y.shift(1)
activity["lag2"] = y.shift(2)
activity["mean7_l1"] = y.shift(1).rolling(7).mean()
activity["mean28_l1"] = y.shift(1).rolling(28).mean()

maes = []
for train_idx, test_idx in tscv.split(activity):
    train, test = activity.iloc[train_idx], activity.iloc[test_idx]
    features = ["day_mapped", "is_sat", "lag1", "lag2", "mean7_l1", "mean28_l1"]

    lgb_model = lgb.LGBMRegressor(
        objective="l1",
        n_estimators=50,
        min_child_samples=20,
        num_leaves=4,
        learning_rate=0.05,
    )
    lgb_model.fit(train[features], train["play_count"])

    lgb_preds = lgb_model.predict(test[features])
    maes.append(mean_absolute_error(test["play_count"], lgb_preds))

print(f"MAE: {np.mean(maes)}")


if len(train) < 56 or train["Day"].nunique() != 7:  # less than 8 weeks
    formula = "play_count ~ 1"  # niveau only
else:
    formula = "play_count ~ 0 + C(Day)"


def fit_nb_weekday(train):
    means = train.groupby("Day", observed=True)["play_count"].mean().clip(lower=0.1)
    start = np.append(np.log(means.values), 0.5)
    m = smf.negativebinomial(formula, data=train).fit(
        start_params=start, method="bfgs", maxiter=1000, disp=0
    )
    if not m.mle_retvals["converged"]:
        raise RuntimeError("NegBin-Fit didn't converge")
    return m


tscv = TimeSeriesSplit(n_splits=40, test_size=7)
n_folds2, p_folds2, lo_folds2, hi_folds2 = [], [], [], []

for i, (train_index, test_index) in enumerate(tscv.split(activity["played_date"])):
    print(f"Fold {i}:")
    # print(f"  Train: index={train_index}")
    # print(f"  Test:  index={test_index}")

    assert activity.iloc[test_index]["Day"].eq("Saturday").sum() == 1

    m = fit_nb_weekday(activity.iloc[train_index])
    mu = m.predict(activity.iloc[test_index])  # point prediction
    alpha = m.params["alpha"]  # dispersion

    n = 1 / alpha
    p = n / (n + mu)
    lo = nbinom.ppf(0.10, n, p)  # 80-%-interval
    hi = nbinom.ppf(0.90, n, p)
    n_folds2.append(n)
    p_folds2.append(p)
    lo_folds2.append(lo)
    hi_folds2.append(hi)

# Erwartungswert aus n und p zurückrechnen: mu = n * (1 - p) / p
mu_all = np.concatenate(
    [
        n_i * (1 - p_i.to_numpy()) / p_i.to_numpy()
        for n_i, p_i in zip(n_folds2, p_folds2)
    ]
)
lo_all = np.concatenate(lo_folds2)
hi_all = np.concatenate(hi_folds2)

y = activity["play_count"].iloc[-280:].to_numpy()
sat = activity["is_sat"].iloc[-280:].to_numpy() == 1

assert len(mu_all) == len(lo_all) == len(hi_all) == len(y) == 280


def interval_score(y, l, h, a=0.2):
    return (h - l) + (2 / a) * np.maximum(l - y, 0) + (2 / a) * np.maximum(y - h, 0)


hit = (y >= lo_all) & (y <= hi_all)
score = interval_score(y, lo_all, hi_all)
below = y < lo_all
above = y > hi_all

print("MAE:      ", np.abs(y - mu_all).mean())
print("RMSE:     ", np.sqrt(((y - mu_all) ** 2).mean()))
print(
    "Coverage: ", hit.mean(), "| Sa:", hit[sat].mean(), "| Nicht-Sa:", hit[~sat].mean()
)
print(
    "Score:    ",
    score.mean(),
    "| Sa:",
    score[sat].mean(),
    "| Nicht-Sa:",
    score[~sat].mean(),
)
print(
    "unter lo:", below.sum(), "| über hi:", above.sum(), "| Nulltage:", (y == 0).sum()
)
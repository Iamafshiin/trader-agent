import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

TEHRAN = 12600
H = 3600
FINAL_START = 1735677000
EMBARGO = 7 * 86400
FOLD_STARTS = [
    "2021-01-01",
    "2021-07-01",
    "2022-01-01",
    "2022-07-01",
    "2023-01-01",
    "2023-07-01",
    "2024-01-01",
    "2024-07-01",
    "2025-01-01",
]
FEATURES = [
    "ret_1",
    "ret_4",
    "ret_24",
    "ret_72",
    "ret_168",
    "atr_pct",
    "stop_dist",
    "depth_atr",
    "ema_fast_dist",
    "ema_slow_dist",
    "ema_spread",
    "vol_24",
    "vol_ratio",
    "t4_spread",
    "t4_dist",
    "t4_ret_6",
    "hour",
    "weekday",
    "btc_ret_24",
    "btc_ret_168",
    "btc_t4_spread",
    "usdt_ret_168",
    "usdt_ret_720",
    "breadth",
]


def tehran_ts(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").timestamp()) - TEHRAN


def load_hourly(dbs: list[Path]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for db in dbs:
        conn = sqlite3.connect(f"file:{db.as_posix()}?immutable=1", uri=True)
        conn.execute("PRAGMA temp_store = MEMORY")
        df = pd.read_sql_query(
            "SELECT symbol, open_time, open, high, low, close, volume FROM candles"
            " WHERE resolution = '60' ORDER BY symbol, open_time",
            conn,
        )
        conn.close()
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        for sym, g in df.groupby("symbol"):
            out[str(sym)] = g.drop(columns="symbol").set_index("open_time")
    return out


def indicators(g: pd.DataFrame) -> pd.DataFrame:
    c = g["close"]
    f = pd.DataFrame(index=g.index)
    for n in (1, 4, 24, 72, 168):
        f[f"ret_{n}"] = c / c.shift(n) - 1
    prev = c.shift(1)
    ranges = [g["high"] - g["low"], (g["high"] - prev).abs(), (g["low"] - prev).abs()]
    tr = pd.concat(ranges, axis=1)
    atr = tr.max(axis=1).ewm(alpha=1 / 14, adjust=False).mean()
    f["atr"] = atr
    f["atr_pct"] = atr / c
    e20 = c.ewm(span=20, adjust=False).mean()
    e50 = c.ewm(span=50, adjust=False).mean()
    f["ema_fast_dist"] = c / e20 - 1
    f["ema_slow_dist"] = c / e50 - 1
    f["ema_spread"] = e20 / e50 - 1
    lr = np.log(c).diff()
    f["vol_24"] = lr.rolling(24).std()
    f["vol_ratio"] = f["vol_24"] / lr.rolling(168).std()
    f["close"] = c
    t = pd.Series(g.index, index=g.index)
    f["hour"] = ((t + TEHRAN) // H) % 24
    f["weekday"] = ((t + TEHRAN) // 86400 + 4) % 7
    four = four_hour(g)
    f = f.join(four, how="left")
    f[four.columns] = f[four.columns].ffill()
    return f


def four_hour(g: pd.DataFrame) -> pd.DataFrame:
    bucket = g.index - (g.index + TEHRAN) % (4 * H)
    c4 = g["close"].groupby(bucket).last()
    e20 = c4.ewm(span=20, adjust=False).mean()
    e50 = c4.ewm(span=50, adjust=False).mean()
    four = pd.DataFrame(
        {
            "t4_spread": e20 / e50 - 1,
            "t4_dist": c4 / e20 - 1,
            "t4_ret_6": c4 / c4.shift(6) - 1,
        }
    )
    four.index = four.index + 4 * H - H
    return four


def build(signals: pd.DataFrame, hourly: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ind = {s: indicators(g) for s, g in hourly.items()}
    btc, usdt = ind["BTCIRT"], ind["USDTIRT"]
    up = pd.DataFrame({s: (f["t4_spread"] > 0).astype(float) for s, f in ind.items()})
    breadth = up.mean(axis=1)
    rows = []
    for _, sig in signals.iterrows():
        t = int(sig["signal_time"])
        f = ind[sig["symbol"]]
        if t not in f.index:
            continue
        r = f.loc[t]
        row = {k: r[k] for k in r.index if k in FEATURES}
        row["stop_dist"] = (r["close"] - sig["stop"]) / r["close"]
        row["depth_atr"] = (r["close"] - (sig["stop"] + 2 * sig["atr"])) / sig["atr"]
        for name, src, col in (
            ("btc_ret_24", btc, "ret_24"),
            ("btc_ret_168", btc, "ret_168"),
            ("btc_t4_spread", btc, "t4_spread"),
            ("usdt_ret_168", usdt, "ret_168"),
        ):
            row[name] = src[col].get(t, np.nan)
        uc = usdt["close"]
        row["usdt_ret_720"] = uc.get(t, np.nan) / uc.get(t - 720 * H, np.nan) - 1
        row["breadth"] = breadth.get(t, np.nan)
        row.update(
            symbol=sig["symbol"],
            signal_time=t,
            exit_time=int(sig["exit_time"]),
            net_return=float(sig["net_return"]),
            win=int(sig["win"]),
        )
        rows.append(row)
    return pd.DataFrame(rows)


def models() -> dict[str, Any]:
    return {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
        "lightgbm": lgb.LGBMClassifier(
            n_estimators=300,
            learning_rate=0.03,
            num_leaves=7,
            max_depth=3,
            min_child_samples=50,
            reg_lambda=1.0,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            path_smooth=10.0,
            verbose=-1,
            random_state=7,
        ),
    }


def fit_predict(model: Any, train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, float]:
    raw_tr = train[FEATURES].replace([np.inf, -np.inf], np.nan)
    raw_te = test[FEATURES].replace([np.inf, -np.inf], np.nan)
    fill = raw_tr.median().fillna(0)
    x_tr = raw_tr.fillna(fill)
    x_te = raw_te.fillna(fill)
    model.fit(x_tr, train["win"])
    p_tr = model.predict_proba(x_tr)[:, 1]
    p_te = model.predict_proba(x_te)[:, 1]
    return p_te, float(np.median(p_tr))


def purged_train(data: pd.DataFrame, start: int) -> pd.DataFrame:
    return data[(data["signal_time"] < start) & (data["exit_time"] < start - EMBARGO)]


def summarize(test: pd.DataFrame, p: np.ndarray, cut: float) -> dict[str, float]:
    take = p >= cut
    kept = test["net_return"][take]
    skipped = test["net_return"][~take]
    auc = roc_auc_score(test["win"], p) if test["win"].nunique() == 2 else float("nan")
    return {
        "n": int(len(test)),
        "auc": float(auc),
        "take_rate": float(take.mean()),
        "all_mean": float(test["net_return"].mean()),
        "kept_mean": float(kept.mean()) if len(kept) else float("nan"),
        "skipped_mean": float(skipped.mean()) if len(skipped) else float("nan"),
        "all_sum": float(test["net_return"].sum()),
        "kept_sum": float(kept.sum()),
    }


def walk_forward(data: pd.DataFrame) -> dict[str, list[dict[str, float]]]:
    out: dict[str, list[dict[str, float]]] = {name: [] for name in models()}
    bounds = [tehran_ts(d) for d in FOLD_STARTS]
    for lo, hi in zip(bounds[:-1], bounds[1:], strict=True):
        train = purged_train(data, lo)
        test = data[(data["signal_time"] >= lo) & (data["signal_time"] < hi)]
        for name, model in models().items():
            p, cut = fit_predict(model, train, test)
            row = summarize(test, p, cut)
            row["fold_start"] = lo
            row["train_n"] = len(train)
            out[name].append(row)
    return out


def final_test(data: pd.DataFrame) -> dict[str, dict[str, float]]:
    train = purged_train(data, FINAL_START)
    test = data[data["signal_time"] >= FINAL_START]
    out = {}
    for name, model in models().items():
        p, cut = fit_predict(model, train, test)
        out[name] = summarize(test, p, cut)
        core = test["symbol"].isin(["BTCIRT", "ETHIRT", "USDTIRT"]).to_numpy()
        out[f"{name}_core"] = summarize(test[core], p[core], cut)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals", type=Path, nargs="+", required=True)
    parser.add_argument("--db", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    signals = pd.concat([pd.read_csv(p) for p in args.signals], ignore_index=True)
    data = build(signals, load_hourly(args.db)).sort_values("signal_time")
    data.to_csv(args.out.with_suffix(".features.csv"), index=False)
    result: dict[str, Any] = {
        "trials": list(models()),
        "policy": "take if p >= median of training predictions",
        "features": FEATURES,
        "signals": len(data),
        "walk_forward": walk_forward(data[data["signal_time"] < FINAL_START]),
    }
    if args.final:
        result["final_2025_26"] = final_test(data)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for name, folds in result["walk_forward"].items():
        n = sum(f["n"] for f in folds)
        all_sum = sum(f["all_sum"] for f in folds)
        kept_sum = sum(f["kept_sum"] for f in folds)
        kept_n = sum(f["n"] * f["take_rate"] for f in folds)
        aucs = [round(f["auc"], 3) for f in folds]
        print(
            f"{name}: n={n} all_mean={all_sum / n:.4f} kept_mean={kept_sum / kept_n:.4f}"
            f" take={kept_n / n:.2f} auc={aucs}"
        )
        for f in folds:
            print(
                f"  fold {pd.Timestamp(f['fold_start'] + TEHRAN, unit='s').date()}"
                f" n={f['n']} all={f['all_mean']:.4f} kept={f['kept_mean']:.4f}"
                f" skipped={f['skipped_mean']:.4f}"
            )
    if args.final:
        for name, r in result["final_2025_26"].items():
            print(
                f"FINAL {name}: n={r['n']} auc={r['auc']:.3f} all={r['all_mean']:.4f}"
                f" kept={r['kept_mean']:.4f} skipped={r['skipped_mean']:.4f}"
                f" take={r['take_rate']:.2f}"
            )


if __name__ == "__main__":
    main()

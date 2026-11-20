# ML signal filter on tcp-vp-2: first bench

Date: 2026-11-20. Code: `research/ml_filter/bench.py`. Method from `research/ml-signal-filter-model-choice.md`.

## Setup

- Rule signals: `tcp-vp-2` replayed on Nobitex 1h, 2019-10 to 2026-11, over 16 IRT pairs. The rules were chosen on BTC, ETH and USDT only; the other 13 pairs are new to them. 2,025 signals, each labelled win/loss after fees and slippage.
- 24 features at signal time, with no future data: returns over 1–168h, ATR, stop distance, pullback depth, EMA distances and spread, 4h trend, realised volatility, hour and weekday, BTC trend, USDT/IRT pace and market breadth. Volume was dropped because about 80% of old Nobitex 1h candles have zero volume.
- Trials: 2, both fixed in advance with no tuning. Logistic regression (L2, C=0.1) and a small LightGBM (7 leaves, depth 3, 50 per leaf).
- Policy: take a signal when its predicted p is at least the median of the training predictions.
- Validation:
  - Expanding walk-forward over 8 half-year folds, 2021–2024.
  - Training rows are purged when their exit falls within 7 days of a test start.
  - 2025-01-01 to 2026-11 was locked and run once at the end.

## Results

Mean net return per trade:

| | Walk-forward 2021–24 (1,153) | Final 2025–26 (645) | Final, BTC/ETH/USDT only (111) |
|---|---|---|---|
| All signals | +3.92% | −0.04% | +1.55% |
| Logistic, kept (~47%) | +4.95% | **+1.13%** | +2.49% |
| Logistic, skipped | – | −1.03% | +0.72% |
| LightGBM, kept | +3.95% | +0.51% | +1.48% |

- **AUC:** logistic averages 0.55 in walk-forward (0.43–0.66 by fold) and 0.555 on the final test. LightGBM is about 0.50.
- **Final logistic, kept minus skipped:** +2.1 pp per trade. A month-block bootstrap gives a 95% CI of −0.6 to +5.2 pp, with P(≤0) = 0.07.
- **Total profit, final period:** filtered minus unfiltered is +3.5 trade-units, with a 95% CI of −2.6 to +9.3.
- **Total profit, 2021–24:** the filter lowers it (kept 27.4 vs all 45.2 trade-units), because it skips half the trades while the average signal is strongly positive.
- **Largest logistic weights:**
  - Toward skipping: a big 72h run-up, a fast USDT/IRT rise and broad market breadth.
  - Toward taking: a deeper pullback, a wider EMA spread and an up-trending BTC 4h.

## Verdict

- LightGBM adds nothing at this sample size.
- Logistic regression improves per-trade quality in walk-forward and on the locked 2025–26 period, but the effect is not yet statistically solid (P ≈ 0.07). It also cuts total profit in good periods.
- It is not ready to gate trades. Recheck once the 30-day paper study and more history are available. A size-scaling use (smaller positions when p is low) may suit it better than skipping.

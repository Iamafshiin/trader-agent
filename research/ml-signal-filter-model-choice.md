# ML signal filter: model choice

**Checked:** 2026-11-20  
**Scope:** Which model family to use as a take/skip filter (meta-label) on rule signals from the long-only EMA pullback strategy. Inputs: Wallex 15m bars (train), Nobitex 1h bars (validation), hundreds to a few thousand labeled signals, triple-barrier labels after fees, CPU-only 8 GB VPS. Sources are papers and official library docs. Where a source could not be read in full, this is marked **(abstract only)** or **(unverified)**.

## Bottom line

- **Recommended: LightGBM binary classifier, heavily constrained, with sigmoid (Platt) calibration.** Confidence: **medium-high**. Trees are the strongest family on small and medium tabular data ([Grinsztajn et al. 2022](https://arxiv.org/abs/2207.08815); [Shwartz-Ziv & Armon 2021](https://arxiv.org/abs/2106.03253)). Trees and neural nets were the best methods in the main finance benchmark ([Gu, Kelly & Xiu](https://www.nber.org/papers/w25398)). Boosted trees give the best probabilities once calibrated ([Niculescu-Mizil & Caruana 2005](https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting)).
- **Runner-up and required baseline: L2-regularized logistic regression.** Confidence: **high** that it belongs in the pipeline. With a few hundred signals it may tie LightGBM. It is well calibrated without help ([scikit-learn](https://scikit-learn.org/stable/modules/calibration.html)). If LightGBM does not beat it out-of-sample after fees, ship the logistic model.
- **Avoid: LSTM, Transformer, and RL for this filter.** Confidence: **high**. They need far more data than a few thousand events. Deep nets lose to trees on tabular data. RL crypto backtests are prone to false positives from overfitting ([Gort et al. 2022](https://arxiv.org/abs/2209.05559)).
- **Avoid TabPFN in production for now.** It is strong on small data ([Hollmann et al. 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC11711098/)), but it is not tested on time series or drift, it is slow on CPU, and newer weights are non-commercial ([TabPFN repo](https://github.com/PriorLabs/TabPFN)). It is fine as an offline benchmark.
- **The validation method matters more than the model.** Use purged, embargoed CV or CPCV, and report PBO and the Deflated Sharpe Ratio. Most of the risk is in overfitting the backtest, not in the model family.

## Comparison

| Family | Fit for hundreds to a few thousand rows | Probability quality | CPU / 8 GB | Overfit risk | Verdict |
|---|---|---|---|---|---|
| Gradient boosting (LightGBM / XGBoost) | Good when constrained (small `num_leaves`, large `min_data_in_leaf`) | Biased toward the middle (sigmoid shape); fixed well by Platt ([N-M & C 2005](https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting)) | Trivial | Medium; controlled by parameters | **Use** |
| Regularized logistic regression | Best at very small n; few parameters | Well calibrated on its own ([sklearn](https://scikit-learn.org/stable/modules/calibration.html)) | Trivial | Low | **Baseline / fallback** |
| Random forest / ExtraTrees | Good; robust defaults | Under-confident; avoids 0 and 1 ([sklearn](https://scikit-learn.org/stable/modules/calibration.html)); fine after calibration ([N-M & C 2005](https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting)) | Trivial | Low-medium | Good second tree model |
| Small MLP | Weak; loses to trees on tabular data ([Grinsztajn](https://arxiv.org/abs/2207.08815)) | Reasonable ([N-M & C 2005](https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting)) | OK | High at this n | Skip |
| LSTM / Transformer | Needs sequences and much more data | Needs calibration | Heavy | Very high | **Avoid** |
| RL | Wrong tool: the action set is just take/skip, a supervised problem | n/a | Heavy | Very high ([Gort et al.](https://arxiv.org/abs/2209.05559)) | **Avoid** |
| TabPFN | Strong up to 10k rows / 500 features ([Hollmann](https://pmc.ncbi.nlm.nih.gov/articles/PMC11711098/)) | Not assessed here | Slow on CPU ([repo](https://github.com/PriorLabs/TabPFN)) | Unknown under drift | Offline benchmark only |

## Meta-labeling

- **What it is.** A primary model (here, the rule) decides the side. A secondary ML model predicts whether each primary signal will hit its profit barrier, and its probability is used to filter or size the trade. It comes from López de Prado, *Advances in Financial Machine Learning* (Wiley, 2018), ch. 3.6–3.7, alongside the triple-barrier method ([Wiley table of contents](https://catalogimages.wiley.com/images/db/pdf/9781119482086.toc.pdf)). This fits our case exactly: the rule gives high recall, and the filter should raise precision.
- **Evidence (abstract only; the JFDS full texts are paywalled):**
  - Joubert, "Meta-Labeling: Theory and Framework", *JFDS* Summer 2022. Links classification metrics to strategy performance. In a controlled experiment, each meta-labeling component improves strategy metrics, including Sharpe ratio and maximum drawdown ([H&T repo, abstracts](https://github.com/hudson-and-thames/meta-labeling)). Effect sizes were not verified.
  - Meyer, Barziy & Joubert, "Calibration and Position Sizing", *JFDS* Spring 2023. Calibration significantly improves fixed position-sizing rules. Sizing methods that fit their own function on training data gained no significant benefit ([same repo](https://github.com/hudson-and-thames/meta-labeling)).
  - Thumm, Barucca & Joubert, "Ensemble Meta-Labeling", *JFDS* Winter 2022. Ensembles help most when the data has several regimes and nonlinear structure ([same repo](https://github.com/hudson-and-thames/meta-labeling)).
  - Meyer, Joubert & Alfeus, "Model Architectures", *JFDS* Fall 2022. Proposes architectures; the abstract reports no numbers ([same repo](https://github.com/hudson-and-thames/meta-labeling)).
- **Caveat.** This evidence comes mostly from one research group and uses controlled or synthetic setups. Treat it as "it can help", not as a proven gain on our data.

## Tabular data: trees vs deep learning

- On 45 benchmark datasets of about 10K samples, tree models (XGBoost, random forest) stay state-of-the-art even after hyperparameter search. The reasons: neural nets struggle with uninformative features and irregular target functions, and they do not preserve the orientation of the data ([Grinsztajn, Oyallon & Varoquaux, NeurIPS 2022 Datasets & Benchmarks](https://arxiv.org/abs/2207.08815); [NeurIPS page](https://neurips.cc/virtual/2022/poster/55627)). Our data is far smaller than 10K, which makes trees or linear models even more favored.
- XGBoost beat recent deep tabular models on their own datasets and needed much less tuning. An ensemble of XGBoost and deep models did best ([Shwartz-Ziv & Armon 2021](https://arxiv.org/abs/2106.03253)).
- TabPFN (Nature 2025) beats prior methods on datasets up to 10,000 samples and 500 features. Its own listed limits: slower inference than CatBoost (about 0.6 s per prediction on CPU at 10k×10, against about 0.0002 s for CatBoost), and time series and data drift are left as future work ([Hollmann et al., PMC copy](https://pmc.ncbi.nlm.nih.gov/articles/PMC11711098/)). On CPU, older versions limit you to 1,000 samples unless you override the cap. The TabPFN-2.5/2.6 weights are non-commercial ([TabPFN repo](https://github.com/PriorLabs/TabPFN)). The lack of testing under drift is the main reason it is not recommended for a regime-shifting crypto series.

## Financial ML evidence

- **Gu, Kelly & Xiu, *RFS* 33(5), 2020.** Trees and neural nets were the best methods for predicting US equity returns. The gain comes from nonlinear interactions between predictors. The dominant signals were momentum, liquidity, and volatility ([NBER w25398](https://www.nber.org/papers/w25398); [RFS](https://academic.oup.com/rfs/article/33/5/2223/5758276)). Their finding that shallow nets beat deeper ones is known here only from a citing paper ([arXiv 2005.01686](https://arxiv.org/pdf/2005.01686)) **(unverified in the original)**. Note that this used decades of data on thousands of stocks, far more than we have.
- **Crypto, intraday.** On 1–60 min bitcoin horizons, RNNs and gradient boosting did best and all models beat random. Predictability rose with the horizon. But the long-short strategy lost money after transaction costs because holding periods were short ([Jaquart, Dann & Weinhardt, *J. Finance & Data Science* 7, 2021](https://www.econbiz.de/Record/short-term-bitcoin-market-prediction-via-machine-learning/10013162705)) **(abstract only)**. Lesson: judge the model on PnL after fees, not on accuracy.
- **Crypto, daily.** Gradient boosting won on short windows and LSTM on 50-day windows, in a gross-return portfolio test ([Alessandretti et al. 2018](https://arxiv.org/abs/1805.08550)) **(abstract and survey summary only; fee handling unverified)**.
- **RL overfitting.** DRL crypto results reported earlier "may be false positives" from backtest overfitting. The authors reject agents that have a high probability of overfitting ([Gort et al. 2022, arXiv](https://arxiv.org/abs/2209.05559); test window only May–June 2022).

## Validation

- **Purged k-fold + embargo.** Triple-barrier labels overlap in time, so standard k-fold leaks information. Purge training samples whose label windows overlap the test fold, and add an embargo after the test fold ([López de Prado 2018, ch. 7.4, table of contents](https://catalogimages.wiley.com/images/db/pdf/9781119482086.toc.pdf)).
- **Walk-forward.** It tests only one path through history, so it can be noisy. **CPCV** (ch. 12.4) builds many train/test paths and gives a distribution of backtest Sharpe ratios rather than a single value ([same table of contents](https://catalogimages.wiley.com/images/db/pdf/9781119482086.toc.pdf)).
- **Evidence.** In a synthetic controlled study, CPCV had lower PBO than k-fold, purged k-fold, and walk-forward. Purged and standard k-fold performed about the same ([Arian, Norouzi Mobarekeh & Seco, *Knowledge-Based Systems* 2024, DOI 10.1016/j.knosys.2024.112477](https://doi.org/10.1016/j.knosys.2024.112477)) **(abstract only)**.
- **Our setup.** Tune with CPCV on Wallex 15m. Keep a final untouched time block. Then check Nobitex 1h as an out-of-exchange test. Hourly correlation between the exchanges is only 0.59–0.80, so expect lower performance there. Treat the Nobitex result as a robustness check, not as a tuning target.

## Overfitting controls

- **PBO.** Combinatorially symmetric CV (CSCV) estimates the probability that the in-sample best configuration underperforms out-of-sample. Ordinary hold-out checks are unreliable for backtests ([Bailey, Borwein, López de Prado & Zhu, *J. Computational Finance* 20(4), 2017](https://www.risk.net/journal-of-computational-finance/2471206/the-probability-of-backtest-overfitting); [preprint](https://escholarship.org/content/qt4w1110bb/qt4w1110bb.pdf)).
- **Deflated Sharpe Ratio.** Corrects the Sharpe ratio for the number of trials and for non-normal returns (skew, kurtosis) ([Bailey & López de Prado, *JPM* 40(5), 2014](https://doi.org/10.3905/jpm.2014.40.5.094); [preprint](https://escholarship.org/content/qt95t7k79q/qt95t7k79q.pdf)). **Log every configuration tried**, because the number of trials is a required input.
- **Haircut Sharpe.** Convert Sharpe to a t-statistic and adjust its p-value for multiple tests. The haircut is not a flat 50%: it is larger for low-Sharpe strategies ([Harvey & Liu, "Backtesting", *JPM* Fall 2015](https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF)).

## Calibration

- **Platt (sigmoid) is best for small n.** It works best on small samples and keeps the ranking, so AUC is unchanged. Isotonic matches or beats it only above about 1,000 calibration samples, and is more prone to overfitting below that ([scikit-learn](https://scikit-learn.org/stable/modules/calibration.html), citing [Niculescu-Mizil & Caruana 2005](https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting)). With hundreds to a few thousand signals, use **sigmoid**.
- **Boosted trees need calibration.** Max-margin learners such as boosted trees push probabilities away from 0 and 1. After calibration, boosted trees, random forests, and SVMs give the best probabilities ([N-M & C 2005](https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting)). LightGBM uses log loss rather than AdaBoost-style boosting, so the distortion may be smaller. Check reliability curves and Brier score out-of-fold anyway.
- **Calibrate on held-out data only.** Use `CalibratedClassifierCV`, or `FrozenEstimator` with a separate disjoint calibration fold ([scikit-learn](https://scikit-learn.org/stable/modules/calibration.html)). With time series, give it purged time splits, not shuffled k-fold.
- **Calibration matters for us** because the bet-or-size rule uses the probability directly. Calibration gives a significant gain for fixed sizing rules ([Meyer, Barziy & Joubert 2023, abstract](https://github.com/hudson-and-thames/meta-labeling)).

## LightGBM settings for small data

From the official docs ([Parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html), [Tuning](https://lightgbm.readthedocs.io/en/latest/Parameters-Tuning.html)):

| Parameter | Default | Small-data direction |
|---|---|---|
| `num_leaves` | 31 | Lower it (e.g. 4–15); the docs say "use small `num_leaves`" |
| `min_data_in_leaf` | 20 | Raise it; the docs call it "very important" against overfitting, and the right value depends on n and `num_leaves` |
| `max_depth` | -1 (no limit) | Set it (e.g. 3–5) |
| `lambda_l1` / `lambda_l2` / `min_gain_to_split` | 0 | Raise for regularization |
| `bagging_fraction` + `bagging_freq`, `feature_fraction` | off | Turn on subsampling |
| `max_bin` | — | Lower it |
| `extra_trees` | false | Try true |
| `path_smooth` | 0 | Raise it; it smooths leaves that have few samples |
| `monotone_constraints` | none | Optional: encode known directions to reduce variance |

- **Class imbalance.** `is_unbalance` and `scale_pos_weight` are mutually exclusive. The docs warn that `is_unbalance` gives "poor estimates of the individual class probabilities" ([Parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html)). Because we need calibrated probabilities, **do not reweight**. Leave the class ratio as is, calibrate, and set the take threshold on expected PnL after fees.
- **Selection metric.** Choose models by out-of-fold log loss or Brier score, plus PnL after fees at the chosen threshold, not by accuracy.

## Risks / what would change the verdict

1. **Too few signals (under about 300).** Prefer logistic regression with 5–10 features, or just tighten the rules. No ML filter may be reliable at that size.
2. **LightGBM does not beat logistic regression on purged out-of-sample log loss and PnL after fees.** Ship logistic regression; it is simpler and naturally calibrated.
3. **Wallex→Nobitex transfer fails** (for example, the precision gain disappears on Nobitex 1h). The features may be exchange-specific microstructure. Use features that do not depend on bar size or exchange, or train per exchange.
4. **PBO above about 0.5, or a Deflated Sharpe that is not significant.** Treat the filter as noise and do not deploy it.
5. **Far more data (tens of thousands of events, or many pairs pooled).** Revisit an ensemble (GBM + RF + LR) per [Thumm et al.](https://github.com/hudson-and-thames/meta-labeling), and maybe a small MLP. LSTM/RL is still unlikely.
6. **TabPFN gains published, peer-reviewed evidence on time series under drift, with CPU-friendly licensing.** Re-benchmark it.
7. **Evidence gaps.** The JFDS meta-labeling papers and the Jaquart and Arian papers were read as abstracts only. The Gu-Kelly-Xiu "shallow beats deep" point is unverified in the original. None of the evidence is from Iranian exchanges.

## Primary sources

- [Grinsztajn, Oyallon, Varoquaux 2022, arXiv 2207.08815](https://arxiv.org/abs/2207.08815) · [NeurIPS 2022 poster](https://neurips.cc/virtual/2022/poster/55627)
- [Shwartz-Ziv & Armon 2021, arXiv 2106.03253](https://arxiv.org/abs/2106.03253)
- [Hollmann et al. 2025, Nature 637:319 (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11711098/) · [TabPFN repo](https://github.com/PriorLabs/TabPFN)
- [Gu, Kelly, Xiu, NBER w25398](https://www.nber.org/papers/w25398) · [RFS 33(5)](https://academic.oup.com/rfs/article/33/5/2223/5758276)
- [Hudson & Thames meta-labeling repo (JFDS abstracts and links)](https://github.com/hudson-and-thames/meta-labeling)
- [López de Prado 2018, Wiley table of contents](https://catalogimages.wiley.com/images/db/pdf/9781119482086.toc.pdf)
- [Bailey et al., PBO, J. Comp. Finance 2017](https://www.risk.net/journal-of-computational-finance/2471206/the-probability-of-backtest-overfitting) · [preprint](https://escholarship.org/content/qt4w1110bb/qt4w1110bb.pdf)
- [Bailey & López de Prado, Deflated Sharpe Ratio, JPM 2014](https://doi.org/10.3905/jpm.2014.40.5.094) · [preprint](https://escholarship.org/content/qt95t7k79q/qt95t7k79q.pdf)
- [Harvey & Liu, Backtesting, JPM 2015](https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF)
- [Arian, Norouzi Mobarekeh, Seco 2024, KBS](https://doi.org/10.1016/j.knosys.2024.112477)
- [Jaquart, Dann, Weinhardt 2021, JFDS (EconBiz record)](https://www.econbiz.de/Record/short-term-bitcoin-market-prediction-via-machine-learning/10013162705)
- [Alessandretti et al. 2018, arXiv 1805.08550](https://arxiv.org/abs/1805.08550)
- [Gort et al. 2022, arXiv 2209.05559](https://arxiv.org/abs/2209.05559)
- [scikit-learn: Probability calibration](https://scikit-learn.org/stable/modules/calibration.html)
- [Niculescu-Mizil & Caruana, ICML 2005](https://mlanthology.org/icml/2005/niculescumizil2005icml-predicting)
- [LightGBM Parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html) · [LightGBM Parameters Tuning](https://lightgbm.readthedocs.io/en/latest/Parameters-Tuning.html)

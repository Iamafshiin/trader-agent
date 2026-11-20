# ML signal filter: which crypto features to add next

**Checked:** 2026-11-20  
**Scope:** Which feature families have published evidence for predicting short-horizon (hours to days) crypto returns or trend-trade success, which of them we can build from our data or from free public history, and what to add next to the L2 logistic take/skip filter on `tcp-vp-2` signals (Nobitex 1h, 16 IRT pairs, about 2,000 labelled signals, 2019–2026, current out-of-sample AUC about 0.55). Sources are papers and official data docs. Data depths marked **(checked)** were read from the live Binance API or the `data.binance.vision` archive on 2026-11-20. Where a source could not be read in full, this is marked **(abstract only)** or **(unverified)**.

## Bottom line

- **No published family gives a strong, cost-proof edge at a 1h–days horizon on a single coin.** The strongest evidence is cross-sectional and weekly (momentum, size, volatility, trend with volume), not hourly timing on one pair. Expect small AUC gains (0.01–0.03), not a jump. Confidence: **medium-high**.
- **The cheapest new information is global market data from Binance**, which gives full history back to 2017 for price and volume, to 2019–2020 for funding, and to 2020–2021 for open interest **(checked)**. It also fixes the missing-volume problem for the global part of the signal.
- **The Iranian local premium is the most original feature but has the weakest direct evidence.** Papers show local premiums exist and track capital controls and FX stress. One paper finds they predict currency depreciation. **No peer-reviewed paper found shows they predict crypto returns.** Test it, and do not expect much from it.
- **Volume is useful mainly as a conditioner, not on its own.** Abnormal volume predicts *lower* returns in crypto ([Garfinkel, Hsiao & Hu 2023](https://doi.org/10.2139/ssrn.4345640)), and volume changes how strongly recent returns reverse ([Bianchi, Babiak & Dickerson 2022](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)). Binance volume is a fair stand-in for global activity, but not for Nobitex liquidity.

### Ranked shortlist (add in this order)

| # | Feature | Definition (at signal bar close *t*) | Source | History | Evidence | Main leakage risk |
|---|---|---|---|---|---|---|
| 1 | **Abnormal global volume** | `log(vol_24h / median(vol_24h over 30d))` for the coin's Binance USDT pair | Binance spot 1h klines | 2017-08 for BTC **(checked)**; per-coin listing date | Medium: negative abnormal-volume/return link ([Garfinkel et al.](https://doi.org/10.2139/ssrn.4345640)); volume is part of CTREND ([Fieberg et al., JFQA](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178)) | Binance kline open time vs Nobitex bar time; use only bars that closed by *t* |
| 2 | **Return × abnormal volume** | `ret_24h × abnormal_volume` (interaction term; logistic needs it explicit) | As #1 + Nobitex | As #1 | Medium: the interaction "contains significant predictive information" ([Bianchi et al. 2022](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)) | Same as #1 |
| 3 | **Funding rate level and change** | Last settled 8h funding of the coin's Binance USDT-M perp; 3-day mean; and BTC funding as a market feature | Binance `fundingRate` API / archive | BTC 2019-09-10, ETH 2019-11-27, most alts 2020-01, DOGE 2020-07 **(checked)** | Medium for crash risk: high carry "predicts future price crashes" ([Schmeling, Schrimpf & Todorov, BIS WP 1087](https://www.bis.org/publ/work1087.htm)); weak for direct return timing | Use `fundingTime ≤ t` only; the *predicted* next rate is not in history; missing before listing |
| 4 | **Relative strength vs the 16-pair cross-section** | Rank of the pair's 24h and 168h return among the 16 pairs (0–1), and pair return minus BTC return | Nobitex 1h | 2019 | Medium: crypto momentum factor ([Liu, Tsyvinski & Wu, JF 2022](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177)); 2–4 week momentum, reversal after ~1 month ([Dobrynskaya 2023](https://econbiz.de/Record/cryptocurrency-momentum-and-reversal-dobrynskaya-victoria/10014265388)) | Pairs listed later make the rank set change over time; rank only pairs with data at *t* |
| 5 | **Upside / downside semivariance** | Sum of squared positive and negative 1h returns over 7d, each divided by total realized variance; plus the largest 1h jump in 7d | Nobitex 1h (or Binance 1m for cleaner jumps) | 2019 | Medium: higher variance, driven by *positive* jumps, predicts lower returns over the next weeks ([Lee & Wang, JFQA](https://www.scheller.gatech.edu/directory/research/finance/lee/pdf/crypto_variance_leewang_5feb2024.pdf)) | Low; window must end at *t* |
| 6 | **Local BTC premium** | `Nobitex BTC/IRT / (Binance BTC/USDT × Nobitex USDT/IRT) − 1`; level, 24h change, and 30d z-score. Repeat per coin when Binance lists it | Nobitex 1h + Binance 1h | 2019 (Nobitex) | Weak / indirect: premiums track capital controls and open up during rallies ([Makarov & Schoar, JFE 2020](https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:2:p:293-319); [Choi, Lehar & Stauffer](https://snb.ch/dam/jcr:474400ba-255b-49a4-b2b8-5e3626719730/sem_2019_05_31_lehar.n.pdf)); P2P premiums predict FX depreciation ([Niu, arXiv 2410.22443](https://arxiv.org/abs/2410.22443)) | Clock mismatch between exchanges; stale Nobitex closes in thin hours make fake premiums |
| 7 | **Global taker-buy share** | `taker_buy_base_volume / volume` on Binance, summed over 4h and 24h, minus its 30d mean | Binance spot 1h klines (field 10) | 2017-08 **(checked)** | Weak at this horizon: order-flow effects are strong at seconds–minutes ([Bieganowski & Ślepaczuk 2026](https://arxiv.org/abs/2602.00776)); imbalance helps nowcast crashes ([Koutmos & Wei 2023](https://link.springer.com/article/10.1007/s11156-023-01148-1)) **(abstract only)** | Low |
| 8 | **Open-interest change** | 24h and 72h % change in Binance USDT-M open interest (value), and OI / spot 24h volume | `data.binance.vision` daily `metrics` files (5-min rows) | BTC 2020-09-01; alts 2021-12-01 **(checked)**. REST API holds only 1 month ([Binance docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)) | Weak: no peer-reviewed short-horizon test found **(unverified)** | Short history means many missing values for 2019–2021 signals; add a missing flag |
| 9 | **USDT/IRT short shock** | USDT/IRT 24h return and its 30d z-score (we already have 168h/720h) | Nobitex 1h | 2019 | Weak / project-specific: our own model already links a fast USDT/IRT rise to losses ([results.md](ml_filter/results.md)); P2P premium literature ties FX pressure to prices ([Niu](https://arxiv.org/abs/2410.22443)) | Low |
| 10 | **Global attention** | Weekly Google Trends "bitcoin" (worldwide), change vs prior 4 weeks | Google Trends | Monthly from 2004; weekly only for ≤5-year windows ([Google FAQ](https://support.google.com/trends/answer/4365533?hl=en)) | Mixed: Liu & Tsyvinski find attention predicts weekly returns ([RFS 2021](https://econpapers.repec.org/RePEc:oup:rfinst:v:34:y:2021:i:6:p:2689-2727)); Urquhart finds it does not ([Econ. Letters 2018](https://ideas.repec.org/a/eee/ecolet/v166y2018icp40-44.html)) | **High**: each download is rescaled to the window's max, which leaks the future; must be built from rolling past-only windows |

Not on the list: on-chain flows (no free history verified; evidence is weak for BTC), BTC dominance (no free long history found), order book features (our recording started Nov 2026, so there is no training history yet), more calendar features (effects are not persistent).

## Evidence by family

| Family | Best evidence | Holds after costs / out of sample? | Can we build it? | Free history |
|---|---|---|---|---|
| Time-series momentum / trend | Strong at 1–8 weeks ([Liu & Tsyvinski](https://nber.org/papers/w24877)); price/MA ratios forecast daily BTC returns in and out of sample ([Detzel et al. 2021](https://ideas.repec.org/a/bla/finmgt/v50y2021i1p107-137.html)) | OOS yes (Detzel); costs: CTREND survives ([Fieberg et al.](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178)) | Yes, already used | Nobitex 2019 |
| Cross-sectional momentum / reversal | Market, size, momentum factors ([Liu, Tsyvinski & Wu](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177)); momentum to ~4 weeks then reversal ([Dobrynskaya](https://econbiz.de/Record/cryptocurrency-momentum-and-reversal-dobrynskaya-victoria/10014265388)); short-term reversal is liquidity provision, strongest in small, illiquid pairs ([Bianchi et al.](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)) | Mostly gross returns; momentum crashes are severe ([Grobys et al. 2025](https://link.springer.com/article/10.1007/s11408-025-00474-9)) | Yes (16 pairs) | Nobitex 2019 |
| Volatility regime | High realized variance, mostly positive jumps, predicts lower returns ([Lee & Wang](https://www.scheller.gatech.edu/directory/research/finance/lee/pdf/crypto_variance_leewang_5feb2024.pdf)); volatility scaling cuts momentum crashes ([Grobys et al.](https://link.springer.com/article/10.1007/s11408-025-00474-9)) | Cross-sectional, weekly; costs not checked here | Yes | Nobitex 2019 |
| Volume / abnormal volume | Negative abnormal-volume/return link ([Garfinkel et al.](https://doi.org/10.2139/ssrn.4345640)); return × volume predicts ([Bianchi et al.](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)); volume predicts BTC returns except in bull/bear extremes ([Balcilar et al. 2017](https://econpapers.repec.org/RePEc:eee:ecmode:v:64:y:2017:i:c:p:74-81)) | Mixed | Global: yes (Binance). Local: Wallex 1m from 2022 | Binance 2017; Wallex 2022 |
| Order-flow / trade-sign imbalance | Strong at seconds–minutes ([Bieganowski & Ślepaczuk](https://arxiv.org/abs/2602.00776)); crash nowcasting ([Koutmos & Wei](https://link.springer.com/article/10.1007/s11156-023-01148-1)) | Hourly+ evidence thin; profits after costs not reported | Global proxy: Binance taker-buy volume. Local: from Nov 2026 only | Binance 2017 |
| Liquidity (Amihud, spreads) | Illiquid coins earn higher returns ([Zhang & Li 2023](https://ideas.repec.org/a/wly/ijfiec/v28y2023i1p472-492.html)) **(abstract only)** | Cross-sectional, monthly | Amihud needs local volume: not for old Nobitex. Spreads: Nov 2026 only | Weak for us |
| Funding / basis | High carry predicts crashes ([BIS WP 1087](https://www.bis.org/publ/work1087.htm)); perp deviations are large and co-move ([He et al., arXiv 2212.06888](https://arxiv.org/abs/2212.06888)) | Arbitrage profits, not directional timing | Yes (Binance) | 2019-09 (BTC) **(checked)** |
| Open interest | No peer-reviewed short-horizon study found **(unverified)** | Unknown | Yes (archive) | 2020-09 BTC, 2021-12 alts **(checked)** |
| On-chain flows | BTC net inflows mostly do not predict BTC returns; ETH inflows predict lower ETH returns; USDT inflows predict higher BTC/ETH returns at 1–6h ([Chi, arXiv 2411.06327](https://arxiv.org/abs/2411.06327)) | Not stated | Needs paid provider (Glassnode/CryptoQuant) **(free history unverified)** | — |
| Sentiment / attention | Google searches predict weekly returns (+1.84% next week per 1 s.d. for BTC, [CEPR column](https://cepr.org/voxeu/columns/risks-and-returns-cryptocurrencies)); null result in [Urquhart 2018](https://ideas.repec.org/a/eee/ecolet/v166y2018icp40-44.html) | Mixed | Weekly only for long windows | Google Trends 2004 |
| BTC dominance / market factor | Market factor explains much of coin returns ([Liu, Tsyvinski & Wu](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177)) | Risk factor, not timing | BTC trend and breadth: already used. Dominance: CoinGecko chart is paid-only ([docs](https://docs.coingecko.com/reference/global-market-cap-chart)) | — |
| Day-of-week / hour | Return anomalies not persistent; volume patterns are ([Baur et al. 2019](https://ideas.repec.org/a/eee/finlet/v31y2019icp78-92.html)); only BTC Monday effect, mostly not beatable vs random ([Caporale & Plastun](https://bura.brunel.ac.uk/handle/2438/17208)) | No | Already used | — |
| Cross-exchange / local premium | Premiums persist under capital controls ([Makarov & Schoar](https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:2:p:293-319); [Choi et al.](https://snb.ch/dam/jcr:474400ba-255b-49a4-b2b8-5e3626719730/sem_2019_05_31_lehar.n.pdf)); predict FX depreciation ([Niu](https://arxiv.org/abs/2410.22443)) | No return-prediction test found | Yes | Nobitex 2019 + Binance |

## Momentum and trend

- Crypto shows strong time-series momentum, and attention proxies forecast returns ([Liu & Tsyvinski, RFS 34(6) 2021](https://econpapers.repec.org/RePEc:oup:rfinst:v:34:y:2021:i:6:p:2689-2727); [NBER w24877](https://nber.org/papers/w24877)).
- Ratios of price to moving averages forecast daily BTC returns in and out of sample ([Detzel, Liu, Strauss, Zhou & Zhu, Financial Management 50(1)](https://ideas.repec.org/a/bla/finmgt/v50y2021i1p107-137.html)) **(abstract only)**. We already have EMA distances, so this family is mostly covered.
- CTREND combines price and volume indicators across horizons. It survives transaction costs and holds in big, liquid coins ([Fieberg et al., JFQA](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178)). The abstract does not say "out of sample"; it says robust across subperiods.
- Momentum works best among large coins ([Liu, Tsyvinski & Wu, JF 77(2)](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177)). Many of our 16 pairs are small on Nobitex, so a pair-size or liquidity proxy may matter.
- Volume-weighted time-series momentum is said to be profitable among liquid coins (Huang, Sangiorgi & Urquhart, cited secondhand in [Grobys et al.](https://link.springer.com/article/10.1007/s11408-025-00474-9)) **(unverified; original not found)**.

## Short-term reversal

- Short-term reversal pays for liquidity provision, and it is strongest in smaller, more volatile, less liquid pairs ([Bianchi, Babiak & Dickerson, JBF 142, 2022, working paper read](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)).
- Momentum lasts about 2–4 weeks, and reversal starts after about one month, driven by past losers ([Dobrynskaya, J. Alternative Investments 2023](https://econbiz.de/Record/cryptocurrency-momentum-and-reversal-dobrynskaya-victoria/10014265388)) **(abstract only)**.
- **Fit with our model:** our filter already learned that a big 72h run-up points to "skip" ([results.md](ml_filter/results.md)). That fits a reversal or crowding story. The volume interaction (#2) tests whether the run-up is worse when volume is abnormal.

## Volatility regime

- Coins with higher realized variance earn lower returns in later weeks. The effect comes from positive jumps and jump-robust variance, and is larger in small, illiquid, retail-heavy coins ([Lee & Wang, JFQA, 2024 version](https://www.scheller.gatech.edu/directory/research/finance/lee/pdf/crypto_variance_leewang_5feb2024.pdf)). This suggests splitting our realized vol into up and down parts (#5).
- Volatility scaling reduces crypto momentum crashes but does not change the tail shape ([Grobys, Kolari et al., FMPM 2025](https://link.springer.com/article/10.1007/s11408-025-00474-9)) **(abstract only)**. For a filter, this argues for vol features as "skip in crash-prone regimes", not as return predictors.

## Volume and turnover

- **Abnormal volume predicts lower returns** in crypto, the opposite of equities. The authors read it as investor disagreement under short-sale limits; the effect disappears once Binance enables margin trading on a coin ([Garfinkel, Hsiao & Hu, SSRN 4345640](https://iro.uiowa.edu/esploro/outputs/workingPaper/The-Negative-Abnormal-Volume-Return-Relation/9984414059502771)) **(abstract only)**. Nobitex is spot-only with weak shorting, so the short-sale-limit story fits our market well.
- **Return × volume** has predictive power in a panel of USD pairs, 2017–2022 ([Bianchi et al.](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)).
- Volume predicts BTC returns except in bull and bear extremes, and does not predict volatility ([Balcilar, Bouri, Gupta & Roubaud, Econ. Modelling 64, 2017](https://econpapers.repec.org/RePEc:eee:ecmode:v:64:y:2017:i:c:p:74-81)). Sample ends 2016.
- **Answer to the volume question:** volume is useful but weak on its own. Its value shows up as abnormal volume and as an interaction with past returns. Binance volume can stand in for *global* activity and attention. It cannot stand in for *Nobitex liquidity*, because local flows come from rial deposits and capital controls, which drive local price gaps ([Makarov & Schoar](https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:2:p:293-319)). Wallex 1m volume (from Feb 2022) is the only local volume history; check how many signals fall after Feb 2022 before using it.

## Order-flow imbalance

- Order-book and trade-flow features predict returns at very short horizons. In a 2026 study on 1-second data, order-flow imbalance has a largely monotone effect, and tradability was checked with taker and maker backtests ([Bieganowski & Ślepaczuk, arXiv 2602.00776](https://arxiv.org/abs/2602.00776)) **(abstract only; net profits not stated)**.
- Order imbalance helps nowcast BTC crash risk ([Koutmos & Wei, RQFA 2023](https://link.springer.com/article/10.1007/s11156-023-01148-1)) **(abstract only)**.
- **For us:** our hold time is days, so the evidence is thin. Binance klines carry taker-buy base volume back to 2017 **(checked)**, so a global imbalance feature costs nothing to test (#7). The Nobitex trades WebSocket started in Nov 2026 and has no training history; use it for monitoring, not for this model, until it has 6–12 months of signals.

## Liquidity

- Less liquid coins (Amihud measure) earn higher returns in the cross-section ([Zhang & Li, IJFE 28(1), 2023](https://ideas.repec.org/a/wly/ijfiec/v28y2023i1p472-492.html)) **(abstract only)**.
- **For us:** Amihud needs local volume, which old Nobitex candles lack. A Binance-based Amihud measures global, not local, liquidity. Spread and depth exist only from Nov 2026. Skip for now.

## Funding rate, basis and open interest

- Crypto carry (futures minus spot) can reach 60% a year. It is driven by trend-chasing small investors and scarce arbitrage capital, and **high carry predicts future price crashes** ([Schmeling, Schrimpf & Todorov, BIS WP 1087, rev. Oct 2025](https://www.bis.org/publ/work1087.htm)). That paper uses the futures basis; funding rates on perps measure the same crowding.
- Perp prices deviate from no-arbitrage values more than in FX; deviations co-move across coins and shrink over time ([He, Manela, Ross & von Wachter, arXiv 2212.06888](https://arxiv.org/abs/2212.06888)).
- No peer-reviewed paper was found that tests open interest as a short-horizon return predictor **(unverified)**.
- **Free history (checked 2026-11-20):**
  - Funding via `GET /fapi/v1/fundingRate` (max 1,000 rows per call) ([Binance docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)). First records: BTCUSDT 2019-09-10, ETHUSDT 2019-11-27, XRP/LTC/ADA/TRX 2020-01, DOGEUSDT 2020-07. Monthly archive files from 2020-01 ([binance-public-data](https://github.com/binance/binance-public-data)).
  - Open interest via REST covers only the last month ([Binance docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)). The `data.binance.vision` daily `metrics` files hold 5-minute rows with `sum_open_interest`, `sum_open_interest_value`, top-trader and taker long/short ratios. They start 2020-09-01 for BTCUSDT and 2021-12-01 for ETH, XRP, LTC, DOGE, ADA, TRX.
- **Fit with our model:** "fast USDT/IRT rise" and "broad breadth" already point to skip, which looks like a crowding signal. Funding is the global crowding measure.

## On-chain

- BTC net inflows to exchanges mostly do not predict BTC returns at 1–6h. ETH inflows predict lower ETH returns. USDT inflows predict higher BTC and ETH returns ([Chi, arXiv 2411.06327](https://arxiv.org/abs/2411.06327)) **(abstract only; data provider not named)**.
- Exchange-flow data normally comes from paid providers. No free hourly history was verified. Skip.

## Sentiment and attention

- One standard deviation more Google searches for bitcoin this week goes with +1.84% return next week ([Liu & Tsyvinski, CEPR column](https://cepr.org/voxeu/columns/risks-and-returns-cryptocurrencies)).
- Realized volatility and volume predict next-day attention, but attention does not predict returns ([Urquhart, Econ. Letters 166, 2018](https://ideas.repec.org/a/eee/ecolet/v166y2018icp40-44.html)) **(abstract only)**.
- **Data:** values are scaled 0–100 within each request, using a sample of searches, with noise for low-volume terms ([Google Trends FAQ](https://support.google.com/trends/answer/4365533?hl=en)). Hourly data exists only for short windows, and daily for windows under about 9 months **(cutoff unverified in official docs)**. Persian-language or Iran-only series are likely noisy because Google use in Iran depends on VPNs **(unverified)**. Rank low.

## Market-wide factors and BTC dominance

- A market factor plus size and momentum explain the cross-section of coin returns ([Liu, Tsyvinski & Wu](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177)). We already use BTC trend, BTC returns and breadth.
- BTC dominance history needs a market-cap feed. CoinGecko's global market-cap chart is not on the free Demo plan ([CoinGecko docs](https://docs.coingecko.com/reference/global-market-cap-chart)). A free proxy is the BTC return minus the mean return of the 16 pairs (part of #4).

## Day-of-week and hour

- Across seven exchanges and 15 million observations, return anomalies by time of day or weekday do not persist; trading volume patterns do ([Baur, Cahill, Godfrey & Liu, FRL 31, 2019](https://ideas.repec.org/a/eee/finlet/v31y2019icp78-92.html)).
- Only BTC showed a weekday effect (higher Monday returns), and trading on it was mostly not better than random ([Caporale & Plastun, FRL 2019](https://bura.brunel.ac.uk/handle/2438/17208)).
- **Action:** hour and weekday are likely noise. Consider dropping them, or replace them with one flag for Iranian weekend and banking hours, when rial on-ramps are closed **(hypothesis, no source)**.

## Iranian market angle: local premium and USDT/IRT

- **What the literature shows:**
  - Price gaps across countries are larger than within them, co-move, and open up during large BTC rallies. The authors tie them to capital controls ([Makarov & Schoar, JFE 135(2), 2020](https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:2:p:293-319)).
  - The kimchi premium averaged 4.73% (Jan 2016–Feb 2018). It rises with volatility, transaction costs and confirmation time, and falls with volume. The effect is about ten times stronger for Korea than for Europe–US gaps ([Choi, Lehar & Stauffer, SNB seminar paper](https://snb.ch/dam/jcr:474400ba-255b-49a4-b2b8-5e3626719730/sem_2019_05_31_lehar.n.pdf)).
  - The kimchi premium reached 20.8% in May 2021 and moved with remittances to China ([Lee & Oh, FRL 50, 2022](https://ideas.repec.org/a/eee/finlet/v50y2022ics1544612322004056.html)).
  - P2P (LocalBitcoins) premiums for 80 currencies are larger under capital controls and fixed FX regimes. They **predict later official-rate depreciation** ([Niu, arXiv 2410.22443](https://arxiv.org/abs/2410.22443)).
- **What is missing:** no peer-reviewed study found tests a local premium as a predictor of crypto returns. Only a media backtest exists for kimchi-premium turning points ([CryptoSlate](https://cryptoslate.com/does-thes-kimchi-premium-still-front-run-btc/)), which is not evidence. No academic paper on a Nobitex premium was found.
- **How to build it:** `premium = Nobitex BTCIRT / (Binance BTCUSDT × Nobitex USDTIRT) − 1`. Nobitex also lists `BTCUSDT` ([our API notes](nobitex-market-data-sources.md)), so a fully internal version, `BTCIRT / (Nobitex BTCUSDT × USDTIRT) − 1`, removes the Binance clock problem. That internal version measures the local IRT market vs the local USDT market. The Binance version measures local vs global.
- **Expected effect:** a high or fast-rising premium means local buyers are paying up. That is the same crowding idea as funding rates. The likely sign is "skip when the premium is high". Treat this as a hypothesis.
- **USDT/IRT:** our model already uses the 168h and 720h pace and finds that a fast rise points to skip. Add a 24h shock (#9). Mind regime breaks: the central bank cut rial payments to exchanges in early 2025 ([Finance Magnates](https://www.financemagnates.com/cryptocurrency/iran-crypto-in-the-dark-trading-volumes-plunge-80-after-strikes/)) **(news source, not primary)**. Those periods will distort the premium.

## Risks / what would change the verdict

1. **Many features, few signals.** With about 2,000 signals and AUC 0.55, ten new features can easily add noise. Add them in the ranked order, one family at a time, and keep a feature only if purged out-of-sample log loss improves. Log each trial for the Deflated Sharpe count (see [model choice](ml-signal-filter-model-choice.md)).
2. **Clock alignment.** Nobitex, Wallex and Binance bars must be aligned on UTC close time. Binance klines are keyed by *open* time; a 1h bar opened at *t*−1h closes at *t*. Spot timestamps are in microseconds from 2025-01-01 ([binance-public-data](https://github.com/binance/binance-public-data)).
3. **Missing history is not random.** Funding starts 2019–2020 and OI starts 2020–2021. Early signals will have NaNs. Use a missing flag plus median fill, or train the derivative features only on the later subset and compare.
4. **Binance listing gaps.** Some of our 16 IRT coins may have no Binance pair or listed late. Check per coin; do not forward-fill a feature before listing.
5. **Stale Nobitex prices.** About 80% of old 1h candles have zero volume, so many closes are stale. A stale close against a live Binance price creates a fake premium. Mask premium values when the Nobitex bar had no trades, or use a 4h/24h median.
6. **Google Trends rescaling** is look-ahead by design. Build it only from rolling past-only downloads, or drop it.
7. **Evidence is mostly cross-sectional and weekly.** Our task is time-series timing on one pair at 1h–days. Effects may not carry over.
8. **Iranian regime shifts** (payment cut-offs, strikes, exchange outages) can flip the sign of local features. Check stability by year.
9. **Evidence gaps.** Garfinkel et al., Dobrynskaya, Detzel et al., Zhang & Li, Urquhart, Koutmos & Wei, Grobys et al. and Chi were read as abstracts only. The Huang–Sangiorgi–Urquhart volume-weighted momentum result is unverified. No source was found for open interest as a short-horizon predictor, or for a local premium predicting returns.

## Primary sources

- [Liu & Tsyvinski, Risks and Returns of Cryptocurrency, RFS 34(6) 2021](https://econpapers.repec.org/RePEc:oup:rfinst:v:34:y:2021:i:6:p:2689-2727) · [NBER w24877](https://nber.org/papers/w24877) · [CEPR column](https://cepr.org/voxeu/columns/risks-and-returns-cryptocurrencies)
- [Liu, Tsyvinski & Wu, Common Risk Factors in Cryptocurrency, JF 77(2) 2022](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177)
- [Fieberg et al., A Trend Factor for the Cross Section of Cryptocurrency Returns, JFQA](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178)
- [Detzel et al., Learning and predictability via technical analysis, Financial Management 50(1)](https://ideas.repec.org/a/bla/finmgt/v50y2021i1p107-137.html)
- [Dobrynskaya, Cryptocurrency Momentum and Reversal, JAI 2023](https://econbiz.de/Record/cryptocurrency-momentum-and-reversal-dobrynskaya-victoria/10014265388)
- [Bianchi, Babiak & Dickerson, Trading volume and liquidity provision, JBF 142 (Riksbank WP 413)](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)
- [Garfinkel, Hsiao & Hu, The Negative Abnormal Volume–Return Relation, SSRN 4345640](https://iro.uiowa.edu/esploro/outputs/workingPaper/The-Negative-Abnormal-Volume-Return-Relation/9984414059502771)
- [Balcilar et al., Can volume predict Bitcoin returns and volatility?, Econ. Modelling 64 2017](https://econpapers.repec.org/RePEc:eee:ecmode:v:64:y:2017:i:c:p:74-81)
- [Lee & Wang, Variance Decomposition and Cryptocurrency Return Prediction (JFQA)](https://www.scheller.gatech.edu/directory/research/finance/lee/pdf/crypto_variance_leewang_5feb2024.pdf)
- [Grobys et al., Cryptocurrency momentum has (not) its moments, FMPM 2025](https://link.springer.com/article/10.1007/s11408-025-00474-9)
- [Bieganowski & Ślepaczuk, Explainable Patterns in Cryptocurrency Microstructure, arXiv 2602.00776](https://arxiv.org/abs/2602.00776)
- [Koutmos & Wei, Nowcasting bitcoin's crash risk with order imbalance, RQFA 2023](https://link.springer.com/article/10.1007/s11156-023-01148-1)
- [Zhang & Li, liquidity and cryptocurrency returns, IJFE 28(1) 2023](https://ideas.repec.org/a/wly/ijfiec/v28y2023i1p472-492.html)
- [Schmeling, Schrimpf & Todorov, Crypto carry, BIS WP 1087](https://www.bis.org/publ/work1087.htm)
- [He, Manela, Ross & von Wachter, Fundamentals of Perpetual Futures, arXiv 2212.06888](https://arxiv.org/abs/2212.06888)
- [Chi, Return and Volatility Forecasting Using On-Chain Flows, arXiv 2411.06327](https://arxiv.org/abs/2411.06327)
- [Urquhart, What causes the attention of Bitcoin?, Econ. Letters 166 2018](https://ideas.repec.org/a/eee/ecolet/v166y2018icp40-44.html)
- [Baur, Cahill, Godfrey & Liu, Bitcoin time-of-day, day-of-week and month-of-year effects, FRL 31 2019](https://ideas.repec.org/a/eee/finlet/v31y2019icp78-92.html)
- [Caporale & Plastun, The day of the week effect in the cryptocurrency market, FRL](https://bura.brunel.ac.uk/handle/2438/17208)
- [Makarov & Schoar, Trading and arbitrage in cryptocurrency markets, JFE 135(2) 2020](https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:2:p:293-319)
- [Choi, Lehar & Stauffer, Bitcoin Microstructure and the Kimchi Premium](https://snb.ch/dam/jcr:474400ba-255b-49a4-b2b8-5e3626719730/sem_2019_05_31_lehar.n.pdf)
- [Lee & Oh, The Kimchi premium and bitcoin-cashing outlets, FRL 50 2022](https://ideas.repec.org/a/eee/finlet/v50y2022ics1544612322004056.html)
- [Niu, What Do Bitcoin Premiums Measure? Evidence from Global P2P Markets, arXiv 2410.22443](https://arxiv.org/abs/2410.22443)
- Data docs: [binance-public-data](https://github.com/binance/binance-public-data) · [Binance funding rate history](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) · [Binance open interest statistics](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics) · [Google Trends FAQ](https://support.google.com/trends/answer/4365533?hl=en) · [CoinGecko global market cap chart](https://docs.coingecko.com/reference/global-market-cap-chart)

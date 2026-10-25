# Prior-session profiles, time-at-price, and normal overlays

**Wayfinder ticket:** [Research prior-session volume and distribution charts](https://github.com/Iamafshiin/trader-agent/issues/19)  
**Workspace status:** This workspace has no usable Git metadata. `git rev-parse --show-toplevel` failed and the workspace root contains no `.git` entry. This report is therefore a local workspace file; no Git branch or GitHub file permalink could be created here.

## Findings

The user's description combines three separate ideas:

1. **Price-trend analysis** describes price direction over a chosen horizon. A volume or TPO profile does not, by itself, identify the trend.
2. **Where trades occurred at prices** most directly means a **Volume Profile**: it groups traded volume by price over a chosen time window.
3. **Where the market spent time at prices** means a **Market Profile/TPO**: it counts time brackets that traded at each price. TPO is not a count of executed volume or individual trades. Sierra Chart describes TPOs as activity based on time at each price and calls TPO charts Market Profile charts. [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html)
4. A **normal/Gaussian curve** is a statistical model, not another name for either profile. A bell-shaped observed profile does not establish that the underlying data are normally distributed. [NIST: Normal Distribution](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3661.htm) and [NIST: Normal Probability Plot](https://itl.nist.gov/div898/handbook/eda/section3/normprpl.htm)

For the phrase “at the corresponding time yesterday,” the key choice is between a **full prior-session profile** and a **same-clock-time previous-day window**. They answer different questions. A full-session profile describes the previous defined trading session. A same-time window compares only the same elapsed portion of the prior day. The latter is closer to a like-for-like intraday comparison, but its duration, clock, and session rules must be specified.

These are chart mechanics. Any claim that a POC, Value Area, high-volume node, low-volume node, shape, or Gaussian band predicts a future move is a separate trading heuristic. The mechanics alone do not establish that claim or show profitability.

## 1. Keep the three chart concepts separate

| Concept | What is counted by price? | Typical display | What the POC means |
|---|---|---|---|
| **Volume Profile / volume-at-price (VAP)** | Executed volume assigned to each price row during a selected interval. The input may be total volume or, where supported, bid/ask or delta measures. | Horizontal histogram across price rows. | The row with the greatest selected volume measure in that interval. |
| **Market Profile / TPO / time-at-price** | Time brackets in which each price row traded. A bracket can contribute a TPO to each price it visited. | Letters, blocks, or a count histogram, often one column per time bracket. | The row with the greatest TPO count, or greatest volume only if the chart explicitly uses volume for its POC. |
| **Statistical normal/Gaussian overlay** | A chosen numeric sample summarized or modeled using a mean and standard deviation. | A smooth probability-density curve or bands around a center line. | There is no profile POC unless a separate profile is also drawn. A Gaussian curve's center is its mean, not automatically a profile's POC. |

The Sierra Chart TPO documentation distinguishes TPO POC from volume POC and permits a volume profile to be displayed beside a TPO profile. TradingView's official Session Volume Profile documentation describes volume distributed across price levels and a separate POC and Value Area. [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html) · [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)

A useful comparison is to display volume-at-price and time-at-price over the **same** interval. A price row with many TPOs but modest volume means it appeared across many time brackets without necessarily having the largest trade quantity. A row with high volume but fewer TPOs means the selected volume measure accumulated there in fewer brackets. Neither fact, by itself, establishes why price traded there or what happens next. [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html) · [Sierra Chart: Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php)

## 2. Session anchoring and “yesterday”

### Prior-session profile

A prior-session profile aggregates the **whole previous session**. It is not necessarily a calendar day from midnight to midnight. Charting software can define session starts, ends, overnight sessions, custom sessions, and time zones. Sierra Chart notes that session times use a configured time zone, and that a trading day can begin on the prior calendar date. TradingView's Session Volume Profile supports “All,” session phases, and custom session windows; bars outside the selected session are excluded. [Sierra Chart: Chart Session Times](https://www.sierrachart.com/index.php?page=doc/SessionTimes.php) · [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)

This is a sensible reference if the intended question is “what price levels saw the most volume or time during the last completed trading session?” For a continuously traded asset such as crypto, there is no universal exchange-open/close boundary. A strategy must choose and document its own trading-day anchor, including time zone and treatment of weekends.

### Same-clock-time previous-day window

A same-clock-time window uses only an interval from the prior day that corresponds to the current interval. For example, after 60 minutes have elapsed from a chosen session start, compare the current first 60 minutes with the prior session's first 60 minutes. This example is only a definition; it is not a recommended window length or a trading rule.

This is **not** the same as using the prior session's complete profile. It controls for elapsed time within the day, but it can omit later price activity and may have fewer observations. A profile can be built from a fixed start/end interval or from a custom session window. Sierra Chart documents fixed-time and explicit start/end profile periods; TradingView documents custom session windows and row settings. [Sierra Chart: Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php) · [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)

For an apples-to-apples comparison, define the same clock, time zone, elapsed duration, session-day convention, and data resolution for both days. A holiday, missing session, daylight-saving change, exchange outage, or weekend can make “yesterday” ambiguous. The profile tool does not decide which prior period is intended; the strategy must.

## 3. Profile calculations and terms

### Volume-at-price

For a selected interval, the profile assigns volume to price rows and displays a horizontal bar for each row. In a simple tick-level model, the row value is the sum of the selected volume measure for trades whose prices fall in that row. Rows may represent one tick or a group of ticks. TradingView exposes row layout choices and volume choices such as total, up/down, and delta. Sierra Chart exposes a “Ticks Per Volume Bar” setting and separate volume-bar calculation choices. [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/) · [Sierra Chart: Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php)

The input data matters. Sierra Chart says tick or one-second intraday records provide better volume-at-price accuracy. If the source bars cover a wider price range, Sierra Chart describes distributing their volume as an average across the prices in that range. TradingView describes proportionally distributing a bar's volume across profile rows according to price overlap. These are different allocation mechanics; a profile built from coarse bars need not match one built from detailed trade data. [Sierra Chart: Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php) · [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)

### TPO / time-at-price

A TPO profile divides a selected profile period into time brackets. Each TPO marks a price row traded during a bracket. The row count is therefore the number of brackets in which that price was visited, not total traded quantity. Sierra Chart exposes both the overall profile period and the length of each TPO letter/block period, plus the price increment grouped into each row. Its documentation cautions that price increment and tick size affect the display and calculation. [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html)

### POC, Value Area, VAH, and VAL

- **POC (Point of Control):** the price row with the highest value of the chosen profile measure. In a volume profile this is the **volume POC**; in a TPO profile it is the **TPO POC**. These can occur at different prices. [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html)
- **Value Area (VA):** a contiguous price range intended to contain a chosen percentage of the profile measure around the POC. A 70% setting is common as a default in the cited platform documentation, but it is configurable and is not a universal market law. [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/) · [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html)
- **VAH / VAL:** the upper and lower price boundaries of that chosen Value Area. For a volume profile, they are volume-based; for a TPO profile, they are TPO-count-based unless the chart is specifically configured to use volume. Sierra Chart documents separate TPO and volume Value Areas and options to use volume instead of TPO counts for TPO highlighting. [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html)

A common implementation starts with the POC and expands across adjacent price rows until the selected share of the total profile measure is included. Because rows are discrete and implementations can differ in row size, ties, and tie-breaking, check the target platform's specific calculation rather than assuming every platform produces identical VAH/VAL. Sierra Chart documents its calculation options and TradingView makes the target percentage and row layout explicit. [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html#Calculations) · [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)

### HVN and LVN

A **high-volume node (HVN)** is a local peak in volume-at-price; a **low-volume node (LVN)** is a local trough. For a TPO chart, the equivalent visual feature is a peak or valley in TPO counts, not necessarily volume. Sierra Chart exposes peak/valley detection and a sensitivity setting, which shows that these labels depend on row grouping and detection settings. An HVN/LVN is a feature of the selected data and settings, not a guaranteed support or resistance level. [Sierra Chart: Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php) · [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html)

## 4. What a “normal distribution” chart could mean

The phrase could refer to several different things:

1. **A fitted Gaussian density over profile rows.** Choose a sample, estimate its mean `μ` and standard deviation `σ`, and overlay the normal density `f(x) = exp(-(x-μ)^2/(2σ^2)) / (σ√(2π))`. A proper density comparison requires the histogram counts to be normalized by sample size and row width; NIST describes this normalization for density overlays. [NIST: Normal Distribution](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3661.htm) · [NIST: Histogram](https://www.itl.nist.gov/div898/handbook/eda/section3/eda33e.htm)
2. **A mean and standard-deviation band.** This is a center line with upper/lower offsets, not a full probability-density curve. For example, Sierra Chart's VWAP-with-standard-deviation study centers bands on VWAP and computes the bands using its documented volume-weighted variance or standard-deviation settings. Such bands do not, by themselves, prove observations are normally distributed. [Sierra Chart: VWAP with Standard Deviation Lines](https://www.sierrachart.com/index.php?page=doc/StudiesReference.php&ID=108)
3. **A visual bell shape mistaken for a statistical model.** A volume or TPO histogram can look roughly bell-shaped, but it is an empirical profile with discrete price rows and a chosen time window. NIST says a histogram can reveal skewness, outliers, and multiple modes; a normal probability plot is one method for checking whether a sample is approximately normal. [NIST: Histogram](https://www.itl.nist.gov/div898/handbook/eda/section3/eda33e.htm) · [NIST: Normal Probability Plot](https://itl.nist.gov/div898/handbook/eda/section3/normprpl.htm)

The population must be specified before a Gaussian overlay is meaningful. Examples of different populations are trade-level prices, returns, volume-weighted prices, or per-price-row volume. They are not interchangeable. For a profile-row curve, the row heights are volume or TPO counts, while the horizontal axis is price. Fitting a normal curve to **prices** is different from treating the profile's **row heights** as the sample. Normality also assumes a stable distributional model; trading prices and volumes can change across sessions and regimes. NIST recommends checking a normality assumption rather than assuming it. [NIST: Normal Distribution](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3661.htm) · [NIST: Normal Probability Plot](https://itl.nist.gov/div898/handbook/eda/section3/normprpl.htm)

## 5. Profile shapes: geometry, not a signal

These shape names are used here as visual shorthand. They describe the profile's outline, not a cause or a forecast. A shape changes when the measure changes from volume to TPO, when the price-row size changes, or when the session/window boundary changes. NIST describes histograms as tools for seeing center, spread, skewness, outliers, and multiple modes; Sierra Chart exposes profile peaks and valleys. [NIST: Histogram](https://www.itl.nist.gov/div898/handbook/eda/section3/eda33e.htm) · [Sierra Chart: Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php)

- **D-like / single central hump:** one broad middle concentration with a roughly balanced outline.
- **P-like:** a larger concentration toward the higher-price end and a thinner tail below it.
- **b-like:** a larger concentration toward the lower-price end and a thinner tail above it.
- **Double distribution / bimodal:** two separate concentrations with a thinner region between them.

These are descriptions only. Do not infer “buyers,” “sellers,” “short covering,” “liquidation,” acceptance, rejection, or future direction from the silhouette alone. Such stories are trader interpretations, and their definitions vary. Use “volume profile shape” or “TPO shape” explicitly so the reader knows which measure formed the outline.

## 6. Common interpretation heuristics — not mechanics or proven rules

The following are examples of market-profile heuristics, not findings established by the chart calculations:

- A practitioner may treat the prior POC or Value Area as a reference zone and watch how current price behaves near it. The calculations only say where the prior profile's maximum and selected share of activity occurred; they do not show that price must return or reverse there. [Sierra Chart: TPO Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html) · [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)
- A practitioner may describe trading inside the prior Value Area as rotation/balance, or sustained trading outside it as acceptance beyond the prior range. Those terms are hypotheses about current behavior, not what the profile calculation measures.
- A practitioner may watch an LVN as a possible fast-travel or reaction area and an HVN as a possible congestion area. The profile identifies local relative concentrations only. It does not encode order-book depth, intent, or guaranteed future reactions.
- A trader may combine the profile with a separate price-trend method. The profile itself is not directional; trend horizon, trend definition, and how it filters a profile-based setup must be specified separately.
- A prior full-session POC/VA and a same-clock-time prior-day profile should not be compared as if they represented the same sample. The first covers a full session; the second covers only a chosen time window.

No profitability claim is made. The user-supplied description is not detailed enough to turn these heuristics into a testable strategy. Treat them as candidate rules to define and validate, not instructions to trade.

## 7. Important limitations

- **Data and venue coverage:** A profile reflects the feed and venue used. It is not automatically a consolidated view of every exchange. Volume profiles also require volume data; TradingView documents that the study reports an error when volume is absent. [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)
- **Resolution and allocation:** Coarse bars may spread volume across price ranges differently from tick-level data. Row size, tick size, missing data, and aggregation method can move the POC and nodes. [Sierra Chart: Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php) · [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)
- **Session definition:** A bad or inconsistent time zone, start/end time, overnight convention, or daylight-saving treatment changes the sample. Session anchoring is part of the calculation, not a cosmetic choice. [Sierra Chart: Chart Session Times](https://www.sierrachart.com/index.php?page=doc/SessionTimes.php)
- **Volume is not direction by itself:** Total volume is not a buyer/seller label. Bid/ask or delta views require suitable source data and a chosen method; they are distinct from total-volume-at-price. [TradingView: Session Volume Profile](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/) · [Sierra Chart: Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php)
- **Developing values change:** A live, incomplete session's profile, POC, and Value Area can change as new data arrives. A backtest must use only values available at the decision time and avoid using the final session profile early.
- **Statistical fit:** A bell curve is a model assumption, not evidence. Test it on the selected sample; NIST's normal probability plot is specifically for assessing approximate normality. [NIST: Normal Probability Plot](https://itl.nist.gov/div898/handbook/eda/section3/normprpl.htm)
- **No performance evidence:** Official chart documentation defines how indicators calculate or display values. It does not establish strategy profitability, robust edge, or suitability for live trading.

## 8. Strategy details still undecided

[Research prior-session volume and distribution charts](https://github.com/Iamafshiin/trader-agent/issues/19) does not settle the following. These choices are needed before the approach can be implemented as a strategy candidate:

1. **Market data:** asset, exchange(s), market-data source, volume availability, required granularity, and treatment of missing/corrected data.
2. **Trend definition:** price inputs, lookback or decision horizon, trend metric, and whether trend is a filter, a setup, or context only.
3. **Reference period:** prior completed trading session, previous calendar day, previous trading day, same-clock-time window, or both. If a window: exact start, length, clock, and how holidays/weekends are handled.
4. **Session anchor:** time zone, day boundary, session hours, overnight inclusion, and whether a 24/7 crypto session is custom-defined.
5. **Profile type and measure:** volume-at-price, TPO, or both; total volume versus bid/ask/delta; TPO bracket duration; price-row/tick size; and row grouping.
6. **Profile statistics:** Value Area percentage, vendor's Value Area and tie-breaking method, POC selection, HVN/LVN sensitivity, and whether developing or completed values are used.
7. **Normal overlay:** whether one is needed at all; sample variable; sample window; weighting; mean/standard-deviation estimator; density normalization; and a normality check.
8. **Decision rules:** exact setup, trigger, invalidation, exit, order type, and whether nodes/VA boundaries are levels, filters, or merely context.
9. **Risk and execution:** position sizing, exposure and loss limits, fees, spread, slippage, liquidity, and fail-safe behavior.
10. **Validation:** leakage-safe historical tests, out-of-sample and walk-forward checks, fee/slippage assumptions, and paper-trading gates before any promotion. No live-trading recommendation is made here.

## Primary sources

- [Sierra Chart — TPO (Time Price Opportunity) Profile Charts](https://www.sierrachart.com/index.php?file=doc/StudiesReference/TimePriceOpportunityCharts.html)
- [Sierra Chart — Volume by Price](https://www.sierrachart.com/index.php?ID=141&Name=Volume_by_Price&l=doc/StudiesReference.php)
- [Sierra Chart — Chart Session Times](https://www.sierrachart.com/index.php?page=doc/SessionTimes.php)
- [Sierra Chart — Volume Value Area Lines](https://www.sierrachart.com/index.php?page=doc/StudiesReference.php&ID=209&Name=Volume_Value_Area_Lines)
- [Sierra Chart — VWAP with Standard Deviation Lines](https://www.sierrachart.com/index.php?page=doc/StudiesReference.php&ID=108)
- [TradingView — Session Volume Profile (official charting-library documentation)](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/session-volume-profile/)
- [NIST/SEMATECH — Normal Distribution](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3661.htm)
- [NIST/SEMATECH — Histogram](https://www.itl.nist.gov/div898/handbook/eda/section3/eda33e.htm)
- [NIST/SEMATECH — Normal Probability Plot](https://itl.nist.gov/div898/handbook/eda/section3/normprpl.htm)
- [NIST/SEMATECH — Approximate intervals that contain most population values](https://www.itl.nist.gov/div898/handbook/prc/section2/prc261.htm)

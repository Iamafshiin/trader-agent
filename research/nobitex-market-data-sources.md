# Nobitex spot market-data sources

**Checked:** 2026-10-24  
**Scope:** Public market-data REST endpoints and public WebSocket channels only. No credentials were used and no private endpoints were called.

## Bottom line

Nobitex exposes spot market data through five public REST endpoints and four public WebSocket channels. REST endpoints are rate-limited per route; WebSocket channels run over Centrifugo and need no token for public data. Key gaps: order-book depth/levels are not documented, OHLC WebSocket updates are only ~10 s, and the symbol format varies by endpoint (uppercase compact `BTCIRT` for market data, lowercase `btc,eth` / `rls,usdt` for stats filters, hyphenated lowercase `btc-rls` in stats-all WebSocket keys).

## REST endpoints

Base host: `https://apiv2.nobitex.ir`  
Testnet: `https://testnetapiv2.nobitex.ir`

| Endpoint | What it returns | Key params | Rate limit |
|---|---|---|---|
| `GET /v3/orderbook/{symbol}` | Full order book (bids/asks, lastUpdate ms, lastTradePrice). `symbol` can be `all`. | `symbol` e.g. `BTCIRT`, `BTCUSDT`, `all` | 300 / min |
| `GET /v2/depth/{symbol}` | Depth data formatted for depth-chart drawing. | `symbol` e.g. `BTCIRT`, `BTCUSDT` | 300 / min |
| `GET /v2/trades/{symbol}` | Up to 20 most recent public trades. `all` **not** supported. | `symbol` e.g. `BTCIRT` | 60 / min |
| `GET /market/stats` | 24 h market stats: best buy/sell, latest, volume, day high/low/change, `isClosed`. | `srcCurrency` (optional, comma-separated, e.g. `btc,eth`), `dstCurrency` (optional, e.g. `rls,usdt`) | 20 / min |
| `GET /market/udf/history` | OHLC candles in TradingView UDF format. | `symbol`, `resolution`, `from`, `to`, `countback`, `page` | 60 / min |

### OHLC details

- Timeframes: `1`, `5`, `15`, `30`, `60`, `180`, `240`, `360`, `720` minutes; `D`, `1D`, `2D`, `3D` days.
- Max 500 candles per request; use `page` for older data.
- `countback` overrides `from` and is capped at 500.
- The docs say 1-minute candles are available from the start of Persian year 1401 (~March 2022). **Observed 2026-11-04 on BTC/IRT:** 1-, 5-, 15-, and 30-minute candles returned `no_data` beyond about 8 days; 60-minute and longer returned data about 1,400 days back, the oldest point probed. ETH/IRT and USDT/IRT are unchecked. See [Choose how to get 12 months of 15-minute evidence](https://github.com/Iamafshiin/trader-agent/issues/40).
- Response fields: `s` (`ok`/`no_data`/`error`), `t`, `o`, `h`, `l`, `c`, `v` arrays; `errmsg` on error.

### Market-stats notes

- If neither `srcCurrency` nor `dstCurrency` is sent, stats for all markets are returned.
- The `global.binance` block is deprecated and scheduled for removal.
- Numeric values are strings in JSON.

## WebSocket channels (public)

Endpoint: `wss://ws.nobitex.ir/connection/websocket`  
Testnet: `wss://testnetws.nobitex.ir/connection/websocket`  
Protocol: Centrifugo. Public channels need no token. Private channels are out of scope for this note.

| Channel pattern | What it streams | Typical cadence |
|---|---|---|
| `public:orderbook-{MARKET_SYMBOL}` | Full order-book snapshot on every book change. | Event-driven; no fixed interval. Low-volume markets can be silent for long periods. |
| `public:candle-{MARKET_SYMBOL}-{RESOLUTION}` | OHLC update for the current candle. | Approximately every 10 seconds. |
| `public:trades-{MARKET_SYMBOL}` | Individual public trades as they execute. | Per trade. |
| `public:market-stats-{MARKET_SYMBOL}` | 24 h stats for one market. | Not explicitly timed; treat as event-driven. |
| `public:market-stats-all` | 24 h stats for all markets, keyed by lowercase hyphenated pair (`btc-rls`). | Not explicitly timed; treat as event-driven. |

`MARKET_SYMBOL` must be uppercase (e.g. `BTCIRT`, `ETHUSDT`). Resolutions match the REST OHLC set.

### WebSocket connection limits

- Max 100 concurrent connections per authenticated user per node (public connections are unauthenticated but count toward client limits).
- Max 450 channels per client connection.
- Server sends empty ping `{}`; direct (non-SDK) clients must reply with empty pong `{}` within 20 seconds.
- Official Centrifugo SDKs can use `{ delta: 'fossil' }` for smaller payloads. Do not enable delta unless the client implements Fossil delta reconstruction.

## Supported symbols / formats

- Market-data REST and WebSocket use uppercase compact symbols: `BTCIRT`, `BTCUSDT`, `ETHUSDT`, etc.
- `/market/stats` filters use lowercase currency codes, comma-separated: `srcCurrency=btc,eth`, `dstCurrency=rls,usdt`.
- WebSocket `public:market-stats-all` keys use lowercase hyphenated format: `btc-rls`, `usdt-rls`.
- The docs do not provide a frozen list of available spot markets; discover them via `/market/stats` (no filters) or `/v3/orderbook/all`.

## Rate-limit summary

| API | Limit |
|---|---|
| `/v3/orderbook/{symbol}` | 300 requests / min |
| `/v2/depth/{symbol}` | 300 requests / min |
| `/v2/trades/{symbol}` | 60 requests / min |
| `/market/stats` | 20 requests / min |
| `/market/udf/history` | 60 requests / min |
| WebSocket connections | 100 per authenticated user per node |
| WebSocket channels | 450 per client connection |

## Gaps and caveats for automated trading

1. **Order-book depth is unspecified.** The docs do not state how many bid/ask levels `/v3/orderbook` or the WebSocket `public:orderbook` channel return.
2. **WebSocket orderbook is event-driven, not periodic.** Seed the book with `GET /v3/orderbook/{symbol}` before subscribing, especially for illiquid pairs.
3. **OHLC WebSocket latency.** `public:candle` updates only ~every 10 seconds; do not rely on it for sub-second bar updates.
4. **Recent trades REST is short.** `/v2/trades` returns at most 20 trades with no pagination. For more history, use `/market/udf/history` or the per-trade WebSocket.
5. **Candle history boundary.** Sub-hourly history was observed to reach back only about 8 days, despite the documented 1401 (~March 2022) boundary for 1-minute candles; see OHLC details above.
6. **No documented tick/trade aggregation API.** The public trade feed is the finest-grained trade source.
7. **Deprecated fields.** `marketStats.global.binance` and private-trade `timestamp` are deprecated; use current fields.
8. **Numeric strings.** Prices, amounts, and volumes are returned as strings; parse carefully.
9. **Runtime market config.** Minimums, precision, and active markets come from `/v2/options`; hard-code nothing.
10. **User-Agent.** Bots should send `User-Agent: TraderBot/<name-and-version>` on HTTP calls (recommended, and mandatory for bot login with `captcha=api`).

## Primary sources

- [Market-data OpenAPI spec](https://apidocs.nobitex.ir/openapi/market_data.yaml)
- [WebSocket OpenAPI spec](https://apidocs.nobitex.ir/openapi/websocket.yaml)
- [WebSocket docs index](https://apidocs.nobitex.ir/websocket/وب-سوکت)
- [Market-data docs index](https://apidocs.nobitex.ir/market_data)
- [Orderbook v3 docs](https://apidocs.nobitex.ir/market_data/دریافت-دفتر-سفارشات-نسخه-۳)
- [Depth docs](https://apidocs.nobitex.ir/market_data/دریافت-عمق-بازار)
- [Recent trades docs](https://apidocs.nobitex.ir/market_data/دریافت-معاملات-اخیر)
- [Market stats docs](https://apidocs.nobitex.ir/market_data/آمار-بازار)
- [OHLC docs](https://apidocs.nobitex.ir/market_data/دریافت-داده-های-ohlc)
- [WebSocket connection docs](https://apidocs.nobitex.ir/websocket/websocket-connection)
- [WebSocket orderbook channel docs](https://apidocs.nobitex.ir/websocket/websocket-orderbook-channel)
- [WebSocket candle channel docs](https://apidocs.nobitex.ir/websocket/websocket-candle-channel)
- [WebSocket trades channel docs](https://apidocs.nobitex.ir/websocket/websocket-public-trades-channel)
- [WebSocket market-stats channel docs](https://apidocs.nobitex.ir/websocket/websocket-market-stats-channel)

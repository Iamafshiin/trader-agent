# Verify Nobitex spot-trading API contract

**Checked:** 2026-10-24  
**Scope:** Current official Nobitex API docs and public configuration only. No credentials were read, no private endpoints were called, and no orders were placed.

## Bottom line

The current supported spot contract is the v2 REST API at `https://apiv2.nobitex.ir`, with an official testnet host at `https://testnetapiv2.nobitex.ir`. A trade-only API key can be scoped to `READ,TRADE`; withdrawals use the separate `WITHDRAW` permission. Order acceptance is not a fill, cancel can leave a partial fill, and the docs do **not** promise an idempotent order-create operation. Use the dynamic `/v2/options` config for market precision and minimums instead of hard-coding sample values. [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml) · [API-key guide](https://apidocs.nobitex.ir/api_key/api-key-guide) · [System options](https://apidocs.nobitex.ir/options/get-system-options)

## Evidence and repository Postman reference

The repo has no established research-note directory, so this note uses `research/`. I found no Nobitex Postman collection file in the checked-out workspace. I did not inspect `.env`. Nobitex’s official FAQ links an online Postman collection, but says the current API docs are the full, up-to-date reference; I used the official docs as the contract source rather than treating a collection example as authoritative. [Official FAQ](https://apidocs.nobitex.ir/faq) · [Online Postman collection](https://documenter.getpostman.com/view/5722122/Szmcayjw?version=latest)

The one live API request was the unauthenticated public `GET /v2/options`, which the docs say needs no token. Its purpose is to confirm that configuration is exposed at runtime; this note does not copy its large, changing coin/network payload. [Endpoint docs](https://apidocs.nobitex.ir/options/get-system-options) · [Public response](https://apiv2.nobitex.ir/v2/options)

## Findings

### Authentication and token lifetime

- REST token auth uses `Authorization: Token <token>`. Current login is `POST /v2/auth/login`; bot login uses `captcha=api`, a `User-Agent: TraderBot/<name-and-version>`, and, when required, `X-TOTP`. Normal MFA can return an intermediate `mfaToken` before the final login response. [Login docs](https://apidocs.nobitex.ir/auth/%D9%88%D8%B1%D9%88%D8%AF-%D9%86%D8%B3%D8%AE%D9%87-%DB%B2) · [Auth OpenAPI](https://apidocs.nobitex.ir/openapi/auth.yaml)
- Login success has `expiresIn`; `remember=yes` asks for a persistent token. The current auth spec documents login, legacy login, OTP resend, and logout, but no refresh-token endpoint or refresh grant. Thus, a token-refresh protocol is **not verified**; re-login is the documented acquisition path. The exact persistence lifetime is not specified in the schema. [Auth OpenAPI](https://apidocs.nobitex.ir/openapi/auth.yaml)
- API-key auth is a separate option: send `Nobitex-Key`, `Nobitex-Signature`, and `Nobitex-Timestamp`. The signature is URL-safe Base64 Ed25519 over `timestamp + METHOD + full_path + raw_body`; in production the timestamp must be within 30 seconds of server time. [API-key guide](https://apidocs.nobitex.ir/api_key/api-key-guide)
- The docs warn that over 100 requests with an invalid/expired token from one IP in under 30 minutes can block that IP for the rest of the period. [General API notes](https://apidocs.nobitex.ir/general_notes)

### Key permissions and withdrawal boundary

- `READ` covers reading order status/lists/trades; `TRADE` is required for spot order add/cancel. `WITHDRAW` is a distinct scope. A spot-trading key should omit `WITHDRAW` unless withdrawals are an explicit, separately approved feature. [API-key guide](https://apidocs.nobitex.ir/api_key/api-key-guide) · [Add order](https://apidocs.nobitex.ir/spot_trade/%D8%AB%D8%A8%D8%AA-%D8%B3%D9%81%D8%A7%D8%B1%D8%B4-%D8%AC%D8%AF%DB%8C%D8%AF-%D8%A7%D8%B3%D9%BE%D8%A7%D8%AA) · [Cancel order](https://apidocs.nobitex.ir/spot_trade/%D9%84%D8%BA%D9%88-%D8%B3%D9%81%D8%A7%D8%B1%D8%B4)
- Key scopes and expiry cannot be changed after creation; only the name, description, and IP whitelist can be edited. A key can have an expiry and up to 15 whitelisted IPs. Its private signing key is shown only once at creation. [API-key OpenAPI](https://apidocs.nobitex.ir/openapi/api_key.yaml)
- Withdrawal write/confirm/cancel APIs require `WITHDRAW`; read-only withdrawal history/details use `READ`. The documented crypto flow requests, then confirms a withdrawal; an unwhitelisted destination can require `X-TOTP` when 2FA is enabled, and user-level daily/monthly limits, network enablement, minimum/maximum and amount-step rules also apply. These are independent of spot trading. [Withdrawal OpenAPI](https://apidocs.nobitex.ir/openapi/withdraw.yaml) · [API-key guide](https://apidocs.nobitex.ir/api_key/api-key-guide) · [System options](https://apidocs.nobitex.ir/openapi/options.yaml)

### Symbols, minimum order, and precision

- Order requests use `srcCurrency`, `dstCurrency`, and `amount`; `amount` is denominated in `srcCurrency` and should be sent as a decimal string. For RLS-quoted markets, the documented price unit is rial. Currency casing and market-symbol formatting vary by endpoint: order examples use lowercase currency fields and response `BTC-RLS`/`BTC-USDT`, while public market and WebSocket examples use uppercase compact symbols such as `BTCIRT`/`BTCUSDT`. Follow each endpoint’s own format. [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml) · [Market-data OpenAPI](https://apidocs.nobitex.ir/openapi/market_data.yaml)
- `/v2/options` provides `activeCurrencies`/`allCurrencies` and dynamic `nobitex.minOrders`, `amountPrecisions`, and `pricePrecisions`. `minOrders` is keyed by destination currency; amount and price steps are keyed by uppercase compact market symbol. A `SmallOrder` failure points to the current `minOrders` value. Current values can change, so fetch this public endpoint at runtime; the schema’s sample numbers are examples, not a durable contract. [Options OpenAPI](https://apidocs.nobitex.ir/openapi/options.yaml) · [Spot order errors](https://apidocs.nobitex.ir/openapi/spot_trade.yaml) · [Public options response](https://apiv2.nobitex.ir/v2/options)
- Market stats can return all markets when neither currency filter is supplied; the v3 order-book endpoint also accepts `all`. These are documented public ways to discover current pairs. Do not treat a coin’s display precision as the per-market order step. [Market-data OpenAPI](https://apidocs.nobitex.ir/openapi/market_data.yaml) · [Options OpenAPI](https://apidocs.nobitex.ir/openapi/options.yaml)
- The API does not define a single fixed minimum/precision table in the spec. It defines a runtime configuration contract instead. Whether a given market or account is currently permitted to trade remains account/runtime-specific (`MarketClosed`, `TradingUnavailable`, or `FeatureUnavailable` can be returned). [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml)

### Fees

Nobitex’s official pricing page says spot fees vary by 30-day trading-volume tier, Iranian-fiat market (the pricing page labels it Toman; the order API specifies rial for RLS-quoted prices), Tether market, and maker/taker role; unusually high-volume VIP terms may be personalized. Its listed standard percentages at the time checked are:

| Tier (30-day volume) | Toman maker / taker | Tether maker / taker |
|---|---:|---:|
| Base (< 100 million toman) | 0.25% / 0.25% | 0.10% / 0.13% |
| VIP1 (100–300 million) | 0.17% / 0.20% | 0.095% / 0.12% |
| VIP2 (300 million–1 billion) | 0.15% / 0.19% | 0.09% / 0.11% |
| VIP3 (1–5 billion) | 0.125% / 0.175% | 0.08% / 0.10% |
| VIP4 (5–20 billion) | 0.10% / 0.155% | 0.07% / 0.10% |
| VIP5 (20–80 billion) | 0.09% / 0.145% | 0.065% / 0.095% |
| VIP6 (> 80 billion) | 0.08% / 0.135% | 0.06% / 0.09% |

The page says fees are charged on the traded asset received (for example, BTC when buying with Toman, or Toman when selling BTC), maker and taker rates differ, and volume tiers are recalculated daily. The API exposes accrued `fee` in detailed order/trade data; use that for actual booked amounts rather than assuming a fixed account rate. **Unknown:** the API specs do not expose an account-specific fee-rate endpoint, and the actual user tier cannot be established from public docs. [Official pricing](https://nobitex.ir/pricing/) · [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml)

### Place, query, cancel, and partial-fill behavior

- `POST /market/orders/add` supports `limit` (default), `market`, `stop_market`, `stop_limit`, and OCO (`mode=oco`). Stops require `stopPrice`; OCO requires `price`, `stopPrice`, and `stopLimitPrice`. A successful API response does not mean a trade occurred: the order is validated before being admitted and can be rejected. Market-order `price` is optional but recommended to bound expected execution. [Add-order docs](https://apidocs.nobitex.ir/spot_trade/%D8%AB%D8%A8%D8%AA-%D8%B3%D9%81%D8%A7%D8%B1%D8%B4-%D8%AC%D8%AF%DB%8C%D8%AF-%D8%A7%D8%B3%D9%BE%D8%A7%D8%AA)
- Query via `POST /market/orders/status` using `id` or `clientOrderId` (id wins if both are sent). `GET /market/orders/list` supports filters and pagination. The order object includes `matchedAmount`, `unmatchedAmount`, `partial`, `averagePrice`, and accrued `fee`. `Active` has remaining quantity; `Done` is complete; `Inactive` is a stop order waiting for its trigger. [Status docs](https://apidocs.nobitex.ir/spot_trade/%D9%85%D8%B4%D8%A7%D9%87%D8%AF%D9%87-%D9%88%D8%B6%D8%B9%DB%8C%D8%AA-%D8%B3%D9%81%D8%A7%D8%B1%D8%B4) · [Order-list docs](https://apidocs.nobitex.ir/spot_trade/%D9%81%D9%87%D8%B1%D8%B3%D8%AA-%D8%B3%D9%81%D8%A7%D8%B1%D8%B4-%D9%87%D8%A7%DB%8C-%DA%A9%D8%A7%D8%B1%D8%A8%D8%B1) · [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml)
- Cancel via `POST /market/orders/update-status` with `status=canceled` and `order` or `clientOrderId`. Only `New`, `Active`, and `Inactive` can transition to `Canceled`; OCO cancellation cancels its paired order. Cancellation may fail with HTTP 200 and body `status: failed`, so inspect both. A canceled order may have `matchedAmount > 0`: cancellation stops the remainder, not prior fills. [Cancel docs](https://apidocs.nobitex.ir/spot_trade/%D9%84%D8%BA%D9%88-%D8%B3%D9%81%D8%A7%D8%B1%D8%B4) · [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml)

### Idempotency and safe retry

- `clientOrderId` is optional, max 32 characters, and must be unique among open orders. The default duplicate-order check rejects an identical order sent in the prior 10 seconds; `pro=true` disables that check, so the spec tells clients to use `clientOrderId` to avoid unintended duplicates. The API has `DuplicateOrder` and `DuplicateClientOrderId` error codes. [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml)
- **Not verified:** the docs do not promise that repeating the same create request or `clientOrderId` replays the original response or guarantees exactly-once execution. Also, lookup by `clientOrderId` is documented only for open orders, so a terminal order may need reconciliation through order history/trades or private events. On an ambiguous timeout, do not blindly resend a create; reconcile first. [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml)

### Rate limits and error handling

| Endpoint | Documented limit |
|---|---:|
| Add spot order | 300 per 10 minutes, shared with margin order placement |
| Order status | 300 per minute |
| Order list | 30 per minute |
| Cancel order | 90 per minute |
| User trade list | 30 per minute |

Limits are per endpoint in general, sometimes IP- or user-based; Nobitex may lower them during heavy market load. On HTTP 429, use the response `backOff` seconds before retrying. Repeatedly ignoring limits can block the user token across APIs for two minutes. [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml) · [General API notes](https://apidocs.nobitex.ir/general_notes)

The general error contract is not uniform: many older endpoints can return HTTP 200 with `status: failed`, while others use HTTP 4xx/5xx. Check both HTTP status and JSON body; use the machine `code`, not `message`, for logic. The docs call HTTP 500 a temporary server problem but define no general retry policy for it. For order-create network/server errors, reconcile before retrying because acceptance may be uncertain. [General API notes](https://apidocs.nobitex.ir/general_notes) · [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml)

### WebSocket authentication

- Public channels need no token. For user-private channels, call `GET /auth/ws/token/` (API key requires `READ`), use the returned JWT to authenticate the WebSocket, and use the separate `websocketAuthParam` from the profile in channel names such as `private:orders#...` and `private:trades#...`. The JWT lasts 1,200 seconds; Nobitex shows SDK `getToken` renewal. The auth parameter is not a token and does not need renewal. [Private-token docs](https://apidocs.nobitex.ir/websocket/get-websocket-token) · [WebSocket OpenAPI](https://apidocs.nobitex.ir/openapi/websocket.yaml)
- Production and test endpoints are `wss://ws.nobitex.ir/connection/websocket` and `wss://testnetws.nobitex.ir/connection/websocket`. Limits include 100 authenticated connections per user per node, 450 channels per client, and a 20-second pong response for direct clients. [Connection docs](https://apidocs.nobitex.ir/websocket/websocket-connection)
- Private order events include order status, filled amount, last fill, fees, and rejected-order errors; private trades provide individual fills. These are useful for live updates, but the docs do not say they replace REST reconciliation. [WebSocket OpenAPI](https://apidocs.nobitex.ir/openapi/websocket.yaml)

### Testnet and deprecations

- Nobitex documents a test website/API, and current REST/WebSocket specs list testnet hosts. This verifies that test mode exists; **parity** of balances, limits, symbols, fees, or all features with production is not promised in the docs. [FAQ](https://apidocs.nobitex.ir/faq) · [Spot OpenAPI](https://apidocs.nobitex.ir/openapi/spot_trade.yaml) · [WebSocket OpenAPI](https://apidocs.nobitex.ir/openapi/websocket.yaml)
- Use the current `apiv2.nobitex.ir` docs and `GET /v3/orderbook/{symbol}`. The changelog records the older v2 order book as deprecated; the current market-data spec documents the v3 GET endpoint. The `global.binance` section of market stats is marked deprecated, and private-trade `timestamp` is deprecated in favor of `time`. [Changelog](https://apidocs.nobitex.ir/changelog) · [Market-data OpenAPI](https://apidocs.nobitex.ir/openapi/market_data.yaml) · [WebSocket OpenAPI](https://apidocs.nobitex.ir/openapi/websocket.yaml)
- The withdrawal spec also marks the older Rial withdrawal flow as due for deprecation in favor of the newer co-bank endpoints. This is outside the spot-order contract but relevant when keeping the separate withdrawal capability disabled. [Withdrawal OpenAPI](https://apidocs.nobitex.ir/openapi/withdraw.yaml)

## Unresolved / account-specific

1. No documented REST token-refresh endpoint; the actual lifetime of `remember=yes` tokens is not specified beyond the `expiresIn` field.
2. No exactly-once/idempotency guarantee for order creation and no universal retry policy for ambiguous POST failures.
3. Current pairs, min order values, and precision are runtime data; the specs do not freeze them. Account/market availability and actual fee tier are account-specific.
4. Testnet parity with production is not documented.
5. The repository-supplied Postman collection was not present in this checkout, so it could not be compared. The official FAQ’s linked collection is examples, while the API docs are the stated current reference.

## Primary sources

- [Spot API OpenAPI spec](https://apidocs.nobitex.ir/openapi/spot_trade.yaml)
- [API-key guide and spec](https://apidocs.nobitex.ir/api_key/api-key-guide) · [API-key OpenAPI spec](https://apidocs.nobitex.ir/openapi/api_key.yaml)
- [Auth OpenAPI spec](https://apidocs.nobitex.ir/openapi/auth.yaml)
- [System-options docs and spec](https://apidocs.nobitex.ir/options/get-system-options) · [live public options](https://apiv2.nobitex.ir/v2/options)
- [Market-data OpenAPI spec](https://apidocs.nobitex.ir/openapi/market_data.yaml)
- [Official fee schedule](https://nobitex.ir/pricing/)
- [General API notes](https://apidocs.nobitex.ir/general_notes)
- [WebSocket OpenAPI spec](https://apidocs.nobitex.ir/openapi/websocket.yaml)
- [Withdrawal OpenAPI spec](https://apidocs.nobitex.ir/openapi/withdraw.yaml)
- [Official FAQ and Postman reference](https://apidocs.nobitex.ir/faq)
- [API change log](https://apidocs.nobitex.ir/changelog)

# Runbook

Paper mode only. No command here can place a real order.

## Local (Windows PC)

```
uv sync
uv run python -m trader_agent check-config
uv run python -m trader_agent collect-candles
uv run python -m trader_agent run-paper --run-id shakedown
uv run python -m trader_agent paper-status --run-id shakedown
```

`.env` needs `TRADER_DATA_DIR` (absolute path). Optional: `BALE_BOT_TOKEN`, `BALE_CHAT_ID`.

## VPS setup (Ubuntu 24.04, as root)

```
git clone https://github.com/Iamafshiin/trader-agent.git /opt/trader-agent
bash /opt/trader-agent/deploy/setup.sh
```

This installs `uv`, the `trader` user, `/var/lib/trader-agent` (data), `/etc/trader-agent/env`
(settings, mode 0640), and starts:

| Unit | Role |
|---|---|
| `trader-streams.service` | Records order book, trades, and 15m candle streams 24/7 |
| `trader-candles.timer` | Hourly candle backfill (15m, 1h, 1d) |
| `trader-report.timer` | Daily completeness report at 00:10 UTC |
| `trader-paper.service` | Paper loop; installed but not enabled. Stops `trader-streams` when started |

Add Bale settings to `/etc/trader-agent/env`, then `systemctl restart` the running unit.

## Burn-in (7 days, collection only)

Keep `trader-streams` running. Each day:

```
trader-cli stream-report
```

## Start the paper study

```
systemctl start trader-paper
systemctl enable trader-paper
trader-cli paper-status --run-id study
```

## Emergency controls

| Action | Command |
|---|---|
| Kill switch (stop all orders and the service) | `trader-kill on` |
| Release kill switch | `trader-kill off`, then `systemctl start trader-paper` |
| Halt flag only (service keeps recording) | `trader-cli halt` |
| Clear a risk halt (manual reset only) | `trader-cli reset-risk-halt --run-id study` |

Risk limits: 1% per order, 10% total exposure, 1% daily loss (Tehran day), 5% drawdown.
A risk halt blocks new buys until a manual reset; exits and protective stops still work.

## Bale alerts

1. Create a bot in Bale, put the token in `BALE_BOT_TOKEN`.
2. Send the bot any message.
3. `trader-cli bale-chat-id`, put the id in `BALE_CHAT_ID`.

## Deploy an update

```
sudo -u trader git -C /opt/trader-agent pull --ff-only
sudo -u trader bash -c "cd /opt/trader-agent && ~/.local/bin/uv sync --locked --no-dev"
systemctl restart trader-streams  # or trader-paper
```

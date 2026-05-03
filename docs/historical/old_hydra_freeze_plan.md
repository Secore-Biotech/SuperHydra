# Old HYDRA Freeze Plan

**Date:** 2026-05-01  
**Freeze window:** 2026-05-01 (immediate closures) → 2026-05-15 (full freeze)  
**Author:** Wasseem  

---

## Strategies — close immediately (this weekend)

### L4 Directional ML

**Correction:** L4 has **2 live open positions** (~$40 notional), not 8/$160 as originally estimated. The other records are stale (status=closed with NULL exit_price — data hygiene issue, not real exposure).

Open positions:

| Symbol | Side | Entry Price | Qty | Notional | Opened |
|--------|------|-------------|-----|----------|--------|
| LINKUSDT | long | $9.406 | 2.13 | ~$20.03 | 2026-04-26 07:21 |
| ADAUSDT | long | $0.2515 | 80.0 | ~$20.12 | 2026-04-26 08:03 |

Cumulative closed PnL: **-$18.10** (488 live trades).

**Close commands:**
```bash
# 1. Close LINK position
ssh root@167.71.196.165
python3 -c "
import ccxt, os
from dotenv import load_dotenv
load_dotenv('/root/.env')
ex = ccxt.binanceusdm({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET'),
    'proxies': {'https': os.getenv('BINANCE_PROXY')} if os.getenv('BINANCE_PROXY') else {}
})
# Close LINK long
ex.create_market_sell_order('LINK/USDT:USDT', 2.13, params={'reduceOnly': True})
# Close ADA long
ex.create_market_sell_order('ADA/USDT:USDT', 80.0, params={'reduceOnly': True})
print('Both positions closed')
"

# 2. Verify closure
python3 -c "
import ccxt, os
from dotenv import load_dotenv
load_dotenv('/root/.env')
ex = ccxt.binanceusdm({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET'),
    'proxies': {'https': os.getenv('BINANCE_PROXY')} if os.getenv('BINANCE_PROXY') else {}
})
positions = [p for p in ex.fetch_positions() if float(p['contracts']) > 0]
print(f'Open positions: {len(positions)}')
for p in positions:
    print(f'  {p[\"symbol\"]} {p[\"side\"]} qty={p[\"contracts\"]} uPnL={p[\"unrealizedPnl\"]}')
"

# 3. Set L4 to permanent paper mode
# In /root/hydra/strategies/layer4_live.py, add at top of file:
#   PAPER_MODE = True  # FROZEN 2026-05-01 — old HYDRA freeze
# hydra_flags.json already has PAUSE_L4_ENTRIES=true — keep it.

# 4. Stop L4 service
systemctl stop hydra-layer4
systemctl disable hydra-layer4
```

**Verification:** `fetch_positions()` returns 0 open positions (excluding the L9 0.001 BTC long which is managed separately). Layer4.db open rows updated to closed.

---

### PM Bot Directional Strategies

**Flag status (confirmed set in `/root/polymarket_btc_bot.py`):**
```python
FEAR_FADE_ENABLED  = False  # PAUSED
NORMAL_LAG_ENABLED = False  # PAUSED
BUNDLE_ARB_ENABLED = False  # PAUSED
BOND_ENABLED       = False  # PAUSED
```

All four strategies are already disabled. No new positions will be opened.

**Open position inventory (265 trades, $241.40 deployed):**

| Strategy | Open Trades | Capital Deployed |
|----------|-------------|-----------------|
| BUNDLE_ARB | 257 | $222.30 |
| BOND_STRATEGY | 5 | $10.00 |
| FEAR_FADE | 3 | $9.10 |
| **Total** | **265** | **$241.40** |

Major bundle positions: 2026 FIFA World Cup (~20 countries), Eurovision 2026, The Masters, French Open, assorted event markets. These are all binary outcomes that resolve on known dates — mostly Q2–Q4 2026.

**Action:**
```bash
# Confirm flags are still set (idempotent check)
grep -E '(FEAR_FADE|NORMAL_LAG|BUNDLE_ARB|BOND)_ENABLED' /root/polymarket_btc_bot.py

# Service stays running for bundle redemption only.
# Add freeze comment to bot config:
sed -i 's/^BUNDLE_ARB_ENABLED.*/BUNDLE_ARB_ENABLED = False  # FROZEN 2026-05-01 — redemption only/' /root/polymarket_btc_bot.py
sed -i 's/^BOND_ENABLED.*/BOND_ENABLED       = False  # FROZEN 2026-05-01 — redemption only/' /root/polymarket_btc_bot.py
sed -i 's/^FEAR_FADE_ENABLED.*/FEAR_FADE_ENABLED  = False  # FROZEN 2026-05-01 — no new entries/' /root/polymarket_btc_bot.py
sed -i 's/^NORMAL_LAG_ENABLED.*/NORMAL_LAG_ENABLED = False  # FROZEN 2026-05-01 — no new entries/' /root/polymarket_btc_bot.py
```

**Disposition:** Service remains running to auto-redeem bundles as events resolve. FEAR_FADE and BOND positions ($19.10) will resolve or expire — no manual close needed at these sizes. After all 265 positions resolve, stop service.

---

### Market Maker (MM)

**Current state:** Service running but effectively idle. Balance: $0.05 USDC. All quote cycles log `MM_SKIP_BALANCE` (needs $9.00/trade).

**Action — stop new quoting immediately:**
```bash
# Stop MM service
systemctl stop market-maker
systemctl disable market-maker

# Stop capital watcher (auto-restarts MM when balance > $15)
systemctl stop capital-watcher
systemctl disable capital-watcher

# Disable capital watcher cron
crontab -l | sed '/capital_watcher/s/^/#FROZEN /' | crontab -
```

**Verification:**
```bash
systemctl is-active market-maker    # expect: inactive
systemctl is-active capital-watcher # expect: inactive
```

**Inventory resolution:** 17 unmatched LONG YES positions in low-probability markets remain on-chain. These require Polymarket CLOB/subgraph queries to enumerate and value. This is handled separately (Prompt C from session) — not part of the immediate freeze.

---

### L10–L19 Paper Strategies

All already in PAPER_MODE with services inactive/dead. None has ever produced a live trade.

**Action:**
```bash
# Set CLOSED=true flag in each file
for layer in 10 11 12 13 14 15 16 18 19; do
    file="/root/hydra/strategies/layer${layer}*.py"
    if ls $file 1>/dev/null 2>&1; then
        actual=$(ls $file)
        # Add CLOSED flag after PAPER_MODE line
        sed -i '/^PAPER_MODE/a CLOSED = True  # FROZEN 2026-05-01 — never produced live signal, no clear hypothesis' "$actual"
        echo "Marked closed: $actual"
    fi
done

# Archive code
mkdir -p /root/hydra/archive/frozen_layers
for layer in 10 11 12 13 14 15 16 18 19; do
    file="/root/hydra/strategies/layer${layer}*.py"
    if ls $file 1>/dev/null 2>&1; then
        cp $file /root/hydra/archive/frozen_layers/
    fi
done

# Ensure all services are stopped and disabled
for layer in 5 6 7 8 10 11 12 13 14 15 16 17 18 19; do
    systemctl stop hydra-layer${layer} 2>/dev/null
    systemctl disable hydra-layer${layer} 2>/dev/null
done

# Also stop dead/broken auxiliary services
systemctl stop hydra-param-optimizer paper-trader hydra-var hydra-daily-report hydra-v4-report hydra-retrain 2>/dev/null
systemctl disable hydra-param-optimizer paper-trader hydra-var hydra-daily-report hydra-v4-report hydra-retrain 2>/dev/null
```

**Rationale per layer:**

| Layer | Description | Rationale for closure |
|-------|-------------|----------------------|
| L5 | RL Trading Agent | No live signals, no trained model deployed |
| L6 | Cross-Exchange Arb Scanner | Scanner only, never executed |
| L7 | DeFi Yield on Idle Capital | Dry run only, Aave deposits never live |
| L8 | S&P 500 Equity Paper Trading | Paper only, Alpaca keys unused |
| L10 | Enhanced BTC | Paper duplicate of L9 |
| L11 | Enhanced ETH | Paper only, no hypothesis |
| L12 | Cash-and-Carry Arb | Paper only, never validated |
| L13 | Dollar-Neutral Momentum | Paper only, no edge found |
| L14 | Multi-Coin Funding Arb | Paper duplicate of L1 |
| L15 | (Unnamed) | Paper only, incomplete |
| L16 | Triangular Arb | Paper only, latency-dependent — impossible on this infra |
| L18 | Calendar Spread | Paper only, no edge found |
| L19 | Stablecoin Depeg Watcher | Paper only, event too rare to validate |

---

## Strategies — run for 2 more weeks (validation source for new ledger)

### L1 Funding Carry

**Keep running through 2026-05-15.**

- Current state: 1 open position (APTUSDT neg_carry, $50/leg)
- Cumulative live PnL: $1.25 (165 funding events, 44 positions)
- Capital deployed: ~$100 (two legs × $50)
- Purpose: provides live Binance funding payment stream for ledger replay testing in SuperHydra

**Cap enforcement:**
```bash
# Verify current deployment is within $100 cap
# L1 uses POSITION_SIZE_USDT = 50 per leg, MAX_OPEN_PAIRS = 2
# Total max deployment = 2 pairs × 2 legs × $50 = $200
# Reduce to 1 pair max:
sed -i 's/MAX_OPEN_PAIRS\s*=\s*2/MAX_OPEN_PAIRS = 1  # FREEZE CAP: $100 max deployed/' /root/hydra/strategies/layer1_live.py
systemctl restart hydra-layer1
```

**Freeze date action (2026-05-15):**
```bash
systemctl stop hydra-layer1
systemctl disable hydra-layer1
# Close any remaining Binance positions manually via ccxt
```

---

### L9 BYC EBTC

**CRITICAL CORRECTION:** L9 has `PAPER_MODE = False` (line 65 of `layer9_ebtc.py`). It is **live**, not paper. It is currently holding a 0.001 BTC long (~$78) on Binance Futures with a stop-loss at entry × 0.92.

**Immediate action — revert to paper mode:**
```bash
# Set PAPER_MODE back to True
sed -i 's/^PAPER_MODE\s*=\s*False/PAPER_MODE = True  # FROZEN 2026-05-01 — reverted to paper for freeze window/' /root/hydra/strategies/layer9_ebtc.py
systemctl restart hydra-layer9
```

**Keep running in paper mode through 2026-05-15.** Provides BYC composite signal data (Trend, Momentum, Carry, Volatility components) for SuperHydra signal validation.

**The 0.001 BTC long position ($78 notional):** This position predates L9 wiring (placed manually). Decision: hold through freeze window — the stop-loss at 0.92× entry protects downside. Close manually on 2026-05-15 or when the BYC signal flips RISK_OFF, whichever comes first.

**Freeze date action (2026-05-15):**
```bash
systemctl stop hydra-layer9
systemctl disable hydra-layer9
# Close BTC position if still open:
python3 -c "
import ccxt, os
from dotenv import load_dotenv
load_dotenv('/root/.env')
ex = ccxt.binanceusdm({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET'),
    'proxies': {'https': os.getenv('BINANCE_PROXY')} if os.getenv('BINANCE_PROXY') else {}
})
ex.create_market_sell_order('BTC/USDT:USDT', 0.001, params={'reduceOnly': True})
"
```

### Other services to keep during validation window

| Service | Action | Reason |
|---------|--------|--------|
| L2 Contrarian Momentum | **Stop immediately** | No ledger value, PnL source unverified (HIGH risk per postmortem) |
| Shadow V3 | **Stop immediately** | V4 decision moot after freeze |
| Academic Factors | **Stop immediately** | Research service, no live trading |
| AI Assessor | **Stop immediately** | Feeds PM bot which is frozen |
| Arb Scanner | **Stop immediately** | L6 scanner, never executed trades |
| PM Bot | **Keep running** | Bundle redemption (265 positions, $241.40) |
| Telegram alerts | **Keep running** | Needed for freeze monitoring |

```bash
# Stop unnecessary services immediately
systemctl stop hydra-layer2 hydra-shadow-v3 hydra-academic-factors ai-assessor arb-scanner
systemctl disable hydra-layer2 hydra-shadow-v3 hydra-academic-factors ai-assessor arb-scanner
```

---

## Data exports required before shutdown

AWS CLI must be installed first. No S3 or backup infrastructure currently exists.

### Setup

```bash
# Install AWS CLI
apt-get update && apt-get install -y awscli

# Configure (Wasseem to provide credentials)
aws configure
# Region: ap-southeast-1 (Singapore, same as server)
# Bucket name: hydra-archive-2026
aws s3 mb s3://hydra-archive-2026
```

### Export manifest

| Export | Source | Destination | Command |
|--------|--------|-------------|---------|
| All databases | 38 .db files across /root/ and /root/hydra/data/ | `s3://hydra-archive-2026/databases/` | See below |
| All logs | /root/hydra/logs/, /root/market_maker.log, /root/bot.log | `s3://hydra-archive-2026/logs/` | See below |
| Flag state snapshot | /root/hydra/config/hydra_flags.json | `s3://hydra-archive-2026/config/` | See below |
| Corrected portfolio returns | /root/hydra/data/portfolio_daily_returns.csv | `s3://hydra-archive-2026/data/` | See below |
| Postmortems & audits | /root/hydra/docs/ | `s3://hydra-archive-2026/docs/` | See below |
| Strategy source code | /root/hydra/strategies/, /root/*.py | `s3://hydra-archive-2026/code/` | See below |
| Research models | /root/hydra/research/models/ | `s3://hydra-archive-2026/models/` | See below |
| .env (secrets) | /root/.env | `s3://hydra-archive-2026/secrets/` (encrypted) | See below |

**Export script** (`/root/hydra/scripts/freeze_export.sh`):
```bash
#!/bin/bash
set -euo pipefail
BUCKET="s3://hydra-archive-2026"
TS=$(date +%Y%m%d_%H%M%S)

echo "=== HYDRA Freeze Export — $TS ==="

# 1. Database dumps (SQLite → SQL text dumps for portability)
mkdir -p /tmp/hydra_export/databases
for db in $(find /root -maxdepth 3 -name '*.db' 2>/dev/null); do
    name=$(basename "$db" .db)
    echo "Dumping $db → ${name}.sql"
    sqlite3 "$db" ".dump" > "/tmp/hydra_export/databases/${name}.sql" 2>/dev/null || true
    cp "$db" "/tmp/hydra_export/databases/${name}.db"
done
# Also export key tables as CSV
sqlite3 /root/market_maker.db ".headers on" ".mode csv" "SELECT * FROM mm_roundtrips;" > /tmp/hydra_export/databases/mm_roundtrips.csv
sqlite3 /root/market_maker.db ".headers on" ".mode csv" "SELECT * FROM mm_trades;" > /tmp/hydra_export/databases/mm_trades.csv
sqlite3 /root/hydra/data/hydra.db ".headers on" ".mode csv" "SELECT * FROM positions;" > /tmp/hydra_export/databases/l1_positions.csv
sqlite3 /root/hydra/data/hydra.db ".headers on" ".mode csv" "SELECT * FROM funding_events;" > /tmp/hydra_export/databases/funding_events.csv
sqlite3 /root/hydra/data/layer4.db ".headers on" ".mode csv" "SELECT * FROM positions;" > /tmp/hydra_export/databases/l4_positions.csv
sqlite3 /root/trades.db ".headers on" ".mode csv" "SELECT * FROM trades;" > /tmp/hydra_export/databases/pm_trades.csv

# 2. Logs (compressed)
mkdir -p /tmp/hydra_export/logs
tar czf /tmp/hydra_export/logs/hydra_logs.tar.gz /root/hydra/logs/ 2>/dev/null || true
tar czf /tmp/hydra_export/logs/root_logs.tar.gz /root/market_maker.log /root/bot.log 2>/dev/null || true

# 3. Config snapshot
mkdir -p /tmp/hydra_export/config
cp /root/hydra/config/hydra_flags.json /tmp/hydra_export/config/
cp /root/hydra/config/settings.py /tmp/hydra_export/config/ 2>/dev/null || true
# Flag state at freeze time
echo "{\"freeze_ts\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"flags\": $(cat /root/hydra/config/hydra_flags.json)}" > /tmp/hydra_export/config/freeze_state.json

# 4. Portfolio data
mkdir -p /tmp/hydra_export/data
cp /root/hydra/data/portfolio_daily_returns.csv /tmp/hydra_export/data/ 2>/dev/null || true

# 5. Docs (postmortems, audits)
cp -r /root/hydra/docs/ /tmp/hydra_export/docs/

# 6. Code archive
tar czf /tmp/hydra_export/code.tar.gz /root/hydra/strategies/ /root/polymarket_btc_bot.py /root/market_maker.py /root/hydra/scripts/ /root/hydra/alerts/ 2>/dev/null || true

# 7. Research models
tar czf /tmp/hydra_export/models.tar.gz /root/hydra/research/models/ 2>/dev/null || true

# Upload to S3
aws s3 sync /tmp/hydra_export/ "$BUCKET/freeze_${TS}/" --storage-class STANDARD_IA

echo "=== Export complete → $BUCKET/freeze_${TS}/ ==="
```

**Alternative if no AWS credentials available:** Export to a local tarball and scp to local machine:
```bash
tar czf /root/hydra_freeze_2026-05-01.tar.gz /tmp/hydra_export/
# Then from local:
scp -i ~/.ssh/polymarket_key root@167.71.196.165:/root/hydra_freeze_2026-05-01.tar.gz ~/hydra_backup/
```

---

## Open positions accounting

### Binance Futures (L4 + L9)

| Strategy | Symbol | Side | Qty | Entry Price | Est. Mark | Notional | uPnL Est. |
|----------|--------|------|-----|-------------|-----------|----------|-----------|
| L4 | LINKUSDT | long | 2.13 | $9.406 | ~$9.40 | ~$20.03 | ~$0.00 |
| L4 | ADAUSDT | long | 80.0 | $0.2515 | ~$0.25 | ~$20.12 | ~$0.00 |
| L9* | BTCUSDT | long | 0.001 | $74,148.9 | ~$78,300 | ~$78.30 | ~+$4.15 |

*L9 BTC position predates HYDRA — manually placed, not strategy-managed.

**L4 cumulative realized PnL:** -$18.10  
**L4 disposition:** Close both positions this weekend. Expected slippage: <$0.50 at these sizes.

### Binance Spot (L1 Funding)

| Strategy | Symbol | Type | Qty | Entry Funding Rate | Spot Size | Perp Size |
|----------|--------|------|-----|-------------------|-----------|-----------|
| L1 | APTUSDT | neg_carry | 49.54 | -0.000144 | $50 | $50 |

**L1 cumulative realized PnL:** +$1.25  
**L1 disposition:** Run through 2026-05-15. Close at freeze.

### Polymarket (PM Bot + MM inventory)

| Strategy | Type | Open Positions | Capital Deployed | Est. Value |
|----------|------|---------------|-----------------|------------|
| BUNDLE_ARB | bundles | 257 | $222.30 | $0–$222.30* |
| BOND_STRATEGY | binary YES | 5 | $10.00 | $0–$10.00* |
| FEAR_FADE | binary YES | 3 | $9.10 | $0–$9.10* |
| MM inventory | unmatched longs | 17 | ~$48–51 | $0–$100+* |

*All Polymarket positions are binary outcomes. Value depends on resolution. No reliable mark-to-market without on-chain/CLOB queries.

**PM Bot realized PnL:** Not yet computed — requires cross-check against on-chain settlements.  
**PM disposition:** Service runs for auto-redemption. Manual review of MM inventory (Prompt C).

### Freeze NAV Summary

| Component | Value | Confidence |
|-----------|-------|------------|
| **Binance Futures equity** | ~$220 free + $78 BTC position + $40 L4 positions | HIGH (API-verifiable) |
| **Binance L1 spot** | ~$50 (APT spot leg) | HIGH |
| **Polymarket USDC** | $0.05 liquid | HIGH |
| **Polymarket positions** | $241.40 deployed (PM Bot) + $48–51 (MM inventory) | LOW (binary, unresolved) |
| **Total deployed capital** | ~$630–680 | |
| **Total liquid** | ~$220 | |
| **Realized PnL all strategies** | -$18.10 (L4) + $1.25 (L1) + $3.63 (MM) ≈ **-$13.22** | |
| **Unrealized PnL** | ~+$4.15 (BTC) + unknown (Polymarket) | LOW confidence |

**Freeze NAV (best estimate): ~$630–680**

This becomes the starting point for SuperHydra's ledger validation. The range reflects uncertainty in Polymarket position values. On-chain queries (Prompt C) will narrow this to a point estimate.

---

## Kill switch

### PAUSE_L4_ENTRIES
**Stays true permanently.** Already set in `hydra_flags.json`. L4 service will be stopped and disabled after closing the 2 remaining positions.

### Decodo proxy — KILL on 2026-05-15
**Decision: YES, kill after freeze.**
- Cost: ~$85/month
- Currently used by: PM Bot (order routing) and MM (order routing)
- After freeze: PM Bot needs it only for bundle redemption POSTs. Keep alive through 2026-05-15.
- After 2026-05-15: If bundles remain unresolved (FIFA World Cup resolves late 2026), keep proxy alive at minimum tier or route redemption through a cheaper alternative.
- **Action date:** 2026-05-15 if all bundles resolved. Otherwise, downgrade to cheapest Decodo tier and re-evaluate monthly.

### Singapore DigitalOcean server — MIGRATE on 2026-05-15
**Decision: YES, migrate to cheaper VPS after full freeze.**
- Current cost: ~$24/month (s-2vcpu-4gb, sgp1)
- After freeze requirements: only PM Bot for redemption + S3 backup cron
- **Migration plan:**
  1. 2026-05-15: Run freeze_export.sh, verify S3 backup integrity
  2. Snapshot the DigitalOcean droplet ($0.05/GB/month = ~$1.50/month for snapshot)
  3. If bundles still open: resize to $6/month droplet (s-1vcpu-1gb) — sufficient for PM Bot redemption
  4. If all bundles resolved: destroy droplet, keep snapshot for 90 days
  5. SuperHydra runs on new infrastructure (separate planning document)

### Hetzner Helsinki tunnel — INVESTIGATE then KILL
**Decision: INVESTIGATE first.**
- Evidence: `BINANCE_PROXY=socks5h://10.0.0.1:1080` in .env suggests a SOCKS proxy via VPC peer or tunnel
- No Hetzner service/systemd unit found on this server — may be a separate VPS running the tunnel
- **Action:**
  1. Identify the Hetzner instance (check Hetzner console or billing)
  2. After L4 closes and L1 freezes (2026-05-15), Binance API access is no longer needed
  3. Kill Hetzner instance on 2026-05-15
  4. If cost is found before then, document in this plan
- **Estimated cost:** ~$4–5/month (Hetzner CX11 or similar)

### Telegram alert configs
**Preserved for SuperHydra reuse.**
- Bot token: `8075055515:AAF...` (in /root/.env as TELEGRAM_BOT_TOKEN)
- Chat ID: `6696801758` (in /root/.env as TELEGRAM_CHAT_ID)
- Library: `/root/hydra/alerts/telegram_bot.py` — simple `send_alert(message)` function
- Consumers: daily_summary.py, detailed_report.py, capital_watcher.sh, bot_watchdog.sh, L4 circuit breaker
- **Action:** Export telegram_bot.py and credentials to SuperHydra repo. No service changes needed — the bot token works from any server.

---

## Cost reduction confirmation

### Current monthly cost (pre-freeze)

| Item | Monthly Cost |
|------|-------------|
| DigitalOcean droplet (s-2vcpu-4gb, sgp1) | ~$24.00 |
| Decodo proxy (Polymarket routing) | ~$85.00 |
| Hetzner tunnel (Binance SOCKS proxy) | ~$4.50 (est.) |
| Anthropic API (AI assessor) | ~$5.00 (est., usage-based) |
| **Total** | **~$118.50/month** |

### 2-week validation window (2026-05-01 → 2026-05-15)

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| DigitalOcean droplet | $24.00 | Keep as-is |
| Decodo proxy | $85.00 | Needed for PM Bot redemption |
| Hetzner tunnel | $4.50 | Needed for L1 Binance access |
| Anthropic API | $0.00 | AI assessor stopped |
| **Total** | **~$113.50/month** | **~$28.37 for 2 weeks** |

Target was $30/mo for validation window — prorated to $28.37 for the 2-week period. **Meets target** when amortized, though the monthly rate is higher due to Decodo being the dominant cost.

### Post-freeze (after 2026-05-15)

**Scenario A: All Polymarket bundles resolved by 2026-05-15**

| Item | Monthly Cost |
|------|-------------|
| DigitalOcean snapshot storage (~30GB) | ~$1.50 |
| S3 archive storage (~2GB, STANDARD_IA) | ~$0.03 |
| **Total** | **~$1.53/month** |

**Scenario B: Polymarket bundles still open (likely — FIFA resolves late 2026)**

| Item | Monthly Cost |
|------|-------------|
| DigitalOcean droplet (resized to s-1vcpu-1gb) | $6.00 |
| Decodo proxy (minimum tier, if available) | ~$20.00 (est.) |
| **Total** | **~$26.00/month** |

**Scenario C: Move PM Bot redemption to local machine**

| Item | Monthly Cost |
|------|-------------|
| DigitalOcean snapshot storage | ~$1.50 |
| S3 archive storage | ~$0.03 |
| Decodo proxy (for local PM Bot) | ~$20.00 |
| **Total** | **~$21.53/month** |

**Recommendation:** Scenario B for now ($26/month). Re-evaluate after FIFA World Cup group stage completes (~July 2026). Target of <$10/month achievable once bundles resolve and Decodo is cancelled.

---

## Old HYDRA disposition after 2026-05-15

### Code repository
- **Action:** Initialize git repo (done — commit `86f6afe`), add all source code, push to GitHub as private repo `wasseem/hydra-v1-archive`
- **Mark read-only:** Archive the repo on GitHub (Settings → Archive this repository)
- **Preserve:** All strategy code, scripts, alerts, configs, research notebooks

### Logs
- **Retention:** 90 days in S3 (`s3://hydra-archive-2026/logs/`)
- **After 90 days (2026-08-15):** Delete from S3. Set S3 lifecycle rule:
  ```bash
  aws s3api put-bucket-lifecycle-configuration --bucket hydra-archive-2026 --lifecycle-configuration '{
    "Rules": [{
      "ID": "expire-logs-90d",
      "Filter": {"Prefix": "logs/"},
      "Status": "Enabled",
      "Expiration": {"Days": 90}
    }]
  }'
  ```

### Databases
- **Full dump to S3:** SQL text dumps + raw .db files in `s3://hydra-archive-2026/databases/`
- **Retention:** Indefinite (databases are small, ~750MB total, <$0.01/month on S3 IA)
- **Drop on server:** After S3 upload verified with checksums

### Telegram bot
- **Keep alive.** Bot token and chat ID are reusable from any server.
- **Transfer to SuperHydra:** Copy `telegram_bot.py` and credentials to new repo.
- **No service disruption:** Bot responds to the same chat regardless of which server sends messages.

### Wallet 0x83fEe45597D95427C9712dFb13485d269A4F88c7
- **Hold pending MM inventory resolution.**
  - 17 unmatched LONG YES positions must resolve (binary outcomes) or be sold on Polymarket
  - On-chain query (Prompt C) will enumerate exact positions and mark-to-market
  - As positions resolve: USDC accumulates in wallet
- **After all positions resolved:** Transfer remaining USDC balance to new SuperHydra wallet (or same wallet if reused)
- **Estimated resolution timeline:** Most markets resolve Q2–Q3 2026. FIFA World Cup positions may extend to Q4 2026.
- **Private key:** Stored in `/root/.env` as `POLYMARKET_PRIVATE_KEY`. Export to secure vault before server teardown.

---

## Signoff

**Date:** 2026-05-01  
**Kill switch holder:** Wasseem  
**Commitment:** No new strategies, positions, or capital deployments are added to old HYDRA after this date. The system enters managed wind-down. All new development occurs in the SuperHydra repository.

**Freeze date:** 2026-05-15  
**Expected freeze-day NAV:** $2,145.93 (revised 2026-05-02; was ~$630��680, then $705.66, before unredeemed Polymarket wins were discovered)  
**Post-freeze monthly cost:** ~$26/month (Scenario B) until Polymarket bundles resolve, then <$2/month

---

## Amendment: L9 Position Closed — 2026-05-01 22:06 UTC

### Position close record

| Field | Value |
|-------|-------|
| Symbol | BTC/USDT:USDT |
| Side | LONG |
| Qty | 0.001 BTC |
| Entry price | $78,410.00 |
| Close price | $78,221.90 |
| Slippage from mark | $6.05 (mark was $78,215.85 at close) |
| Realized PnL (this trade) | **-$0.1881** |
| Commission | -$0.0391 |
| Net (this trade) | **-$0.2272** |
| Order ID | 1001191606512 |

### L9 cumulative PnL (full audit, filled orders only)

| Trade | Entry | Exit | Realized PnL | Commissions | Net |
|-------|-------|------|-------------|-------------|-----|
| Close pre-existing (not L9) | ~$74,149 | ~$75,500 | +$1.3357 | -$0.0748 | +$1.2609 |
| L9 Trade 1 | $75,547.40 | ~$77,900 | +$2.3714 | -$0.0780 | +$2.2934 |
| L9 Trade 2 | $77,921.30 | ~$78,700 | +$0.7741 | -$0.1172 | +$0.6569 |
| L9 Trade 3 (final close) | $78,410.00 | $78,221.90 | -$0.1881 | -$0.0391 | -$0.2272 |
| Funding fees (62 events) | — | — | +$0.14 | — | +$0.14 |
| **Total** | | | **+$4.4331** | **-$0.3091** | **+$4.1240** |

**Note:** The pre-existing position (+$1.26 net) predates L9 wiring. L9's own trades net: **+$2.86**.

### L9 service disposition

- Service stopped and disabled: `systemctl stop hydra-layer9 && systemctl disable hydra-layer9`
- `PAPER_MODE = True` set with freeze comment
- **Hard freeze gates** injected into `execute_long()` and `execute_close()` — both functions return immediately with `L9_FROZEN` log warning, regardless of PAPER_MODE or any flag value
- BYC signal computation continues if service is restarted (writes to `byc_state.json`) but no orders can be placed

### Updated freeze-day NAV

| Component | Previous estimate | Updated |
|-----------|------------------|---------|
| Binance USDT free | $230.15 | $290.09 (+$59.94 from freed margin) |
| Binance USDT used (L4 + L1 margin) | $108.98 | $49.02 |
| Binance USDT total | $339.20 | $339.19 |
| BTC position (L9) | ~$78.16 (0.001 BTC) | $0.00 (closed) |
| L4 open (LINK + ADA) | ~$40.15 | ~$40.15 (unchanged) |
| L1 open (APT spot) | ~$50.00 | ~$49.05 (mark updated) |
| Polymarket USDC liquid | $0.05 | $0.05 |
| Polymarket positions (PM Bot) | $241.40 | $241.40 |
| Polymarket positions (MM inventory) | $48–51 | $48–51 |
| **Total freeze NAV** | **$630–680** | **$628–681** |

L9 closure realized -$0.23 on the final trade but freed $78 of margin. Net effect on NAV: negligible (position was near breakeven). The NAV range narrows slightly because one uncertain component (BTC mark-to-market) has been converted to cash.

**Realized PnL all strategies (updated):**

| Strategy | Realized PnL |
|----------|-------------|
| L4 Directional ML | -$18.10 |
| L1 Funding Carry | +$1.25 |
| MM (10 roundtrips) | +$3.63 |
| L9 BYC (own trades only) | +$2.86 |
| L9 BYC (incl. pre-existing) | +$4.12 |
| PM Bot | unverified |
| **Total (excl. PM Bot)** | **-$10.26** (using L9 own trades) |

---

## Amendment: Polymarket Wallet Full Accounting — 2026-05-01 22:30 UTC

The "17 unmatched LONG YES positions, $48–51" estimate was wrong by an order of magnitude. The wallet contains **559 positions** with an all-in PnL of **-$1,072.36**. See `/root/hydra/docs/mm_final_pnl.md` for full position-by-position accounting.

### Corrected freeze-day NAV: $705.66 (SUPERSEDED -- see NAV revision 2026-05-02 below)

| Component | Previous | Corrected |
|-----------|----------|-----------|
| Binance Futures USDT total | $339.19 | $339.19 |
| Polymarket (all) | $289–292 | $366.47 |
| **Total** | **$628–681** | **$705.66** (SUPERSEDED -- revised to $2,145.93 on 2026-05-02) |

### Key findings
- Both MM and PM Bot share the same wallet (`POLYMARKET_PRIVATE_KEY`)
- `MM_PRIVATE_KEY` derives to a different, unused address
- 303 positions resolved to $0 (cost: $1,865.58)
- 115 positions won ($801.32 net gain, recycled into new positions)
- 141 positions still active ($366.42 MTM — mostly FIFA WC, Eurovision, elections)
- Catastrophic losses concentrated in 5-min/15-min crypto Up/Down markets

### Impact on freeze cost analysis
No change to monthly infrastructure costs. The Polymarket positions are self-custodied tokens — no ongoing cost to hold them. They resolve as events complete (Eurovision May 2026, FIFA WC June–July 2026, elections throughout 2026, 2028 Dem nomination late 2027–2028).

### Wallet disposition (updated)
Hold wallet as-is. Active positions will resolve over the next 6–24 months. No action required — tokens auto-settle on resolution. PM Bot service stays running for bundle redemption. After all 141 positions resolve, transfer remaining USDC to SuperHydra or withdraw.

---

## NAV revision (2026-05-02)

The freeze-day NAV figure was revised on 2026-05-02 following a comprehensive on-chain audit of the Polymarket wallet (0x83fEe45597D95427C9712dFb13485d269A4F88c7). The original estimate of $705.66 omitted 116 redeemable winning positions sitting unredeemed in the Polymarket Exchange contract on Polygon -- the auto-redeem loop had stopped when the PM Bot was halted on May 1, and these wins were never counted.

### Revised freeze-day NAV: $2,145.93

| Component | Value | Source |
|-----------|-------|--------|
| Binance Futures USDT | $339.19 | fapi account query |
| Polymarket active positions (140, MTM) | $330.65 | Data API (prices moved overnight from $366.42) |
| Polymarket liquid USDC | $0.05 | CLOB balance |
| Polymarket unredeemed winnings (116 positions) | $1,476.04 | Data API redeemable, on-chain in Exchange contract |
| **Total** | **$2,145.93** | |

The $1,476.04 in unredeemed winnings represents 116 resolved markets where our side won. Each winning token redeems for $1.00 USDC. The tokens are held by the Polymarket Exchange contract (not at the EOA directly -- verified via CTF balanceOf returning 0 at EOA, which is expected for escrowed positions).

### Revised lifetime PnL: -$1,073.07

| Metric | Previous (May 1) | Revised (May 2) |
|--------|-----------------|-----------------|
| Freeze-day NAV | $705.66 | $2,145.93 |
| Total deposits | $3,219.00 | $3,219.00 |
| Lifetime PnL | -$2,513.34 | **-$1,073.07** |
| Lifetime return | -78.1% | **-33.3%** |

The -78.1% figure was nonsensical -- it implied the system lost more than the entire Polymarket portfolio. The corrected -33.3% is consistent with the Polymarket all-in PnL of -$1,072 plus small Binance net losses (~-$13 across L1/L4/L9/MM).

### Unredeemed winnings disposition

The unredeemed $1,476.04 is recoverable but redemption is postponed. Tokens do not expire on-chain. Recovery to be attempted from a different residential proxy or trusted-network connection at a future date. Recommended method: Polymarket UI via MetaMask from a non-geoblocked IP. Estimated gas cost: ~0.5 MATIC (~$0.25). Wallet currently has 0 MATIC -- needs top-up before redemption.

**Reference:** /root/hydra-next/docs/decisions/2026-05-02-redemption-audit.md (commit 40d8fb3)

---

## Note: fifth measurement failure in the May 1 chain

The original NAV calculation was a fifth measurement failure in the May 1 audit chain -- winning positions were sitting on-chain unredeemed and uncounted. This is the same class of bug as the MM measurement fiction: a measurement source omitted real value because the redemption auto-loop stopped running before the audit. When the PM Bot was halted on May 1, the auto-redeem loop (which runs every 30 minutes) stopped claiming resolved winning positions. The audit then counted only active (unresolved) positions and liquid USDC, missing the 116 positions that had resolved in our favor but whose tokens had not yet been converted to USDC. The result was a NAV understatement of $1,476 -- nearly 69% of the true Polymarket portfolio value was invisible.

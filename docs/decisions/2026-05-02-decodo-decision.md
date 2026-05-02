# Decision: Decodo Proxy Cancellation

**Date:** 2026-05-02
**Author:** Wasseem
**Decision:** CANCEL TODAY

---

## 1. Decodo usage audit

### Traffic categorization (last 30 days)

| Category | Routed via Decodo? | Count | Status |
|----------|-------------------|-------|--------|
| POST /order (new order placement) | YES | ~157,400 (MM) + ~346 (PM Bot) | Permanently disabled -- services stopped, keys revoked |
| POST /trade (trade execution) | YES | Included above | Permanently disabled |
| GET /markets, /prices (market data) | NO (direct) | Thousands/day | Works from SG without proxy |
| GET /positions, /balance (account reads) | NO (direct) | Hundreds/day | Works from SG without proxy |
| Gamma API (resolution checks) | NO (direct) | ~48/day (every 30 min) | Works from SG without proxy |
| Polygon RPC (on-chain redemption) | NO (direct) | ~5-10/day | Works from SG without proxy |

Decodo proxy traffic in logs: 3 startup messages in market_maker.log, 0 in bot.log. The proxy was configured but produced almost no log output because it was only invoked for order POSTs.

Sample log lines:

```
2026-04-26 08:20:10 [PROXY] Selective routing: POST /order /trade via Decodo NL; all else direct
2026-04-29 13:45:02 [PROXY] Selective routing: POST /order /trade via Decodo NL; all else direct
2026-05-01 10:17:06 [PROXY] Selective routing: POST /order /trade via Decodo NL; all else direct
```

### Selective routing implementation

Both polymarket_btc_bot.py and market_maker.py implement `_SelectiveProxyTransport`:

- **Through Decodo:** Only `POST /order` and `POST /trade` to `clob.polymarket.com`
- **Direct (no proxy):** Everything else -- GET reads, Gamma API, Polygon RPC, Telegram, all non-Polymarket traffic

### Geo-blocking test from Singapore server

| Endpoint | Method | Without Proxy | With Proxy |
|----------|--------|---------------|------------|
| clob.polymarket.com/markets | GET | 200 OK | 200 OK |
| gamma-api.polymarket.com/markets | GET | 200 OK | N/A |
| data-api.polymarket.com/positions | GET | 200 OK | N/A |
| clob.polymarket.com/order | POST | 403 Forbidden | 401 (expected -- no auth) |
| polygon-rpc.com (chain RPC) | POST | 200 OK | N/A |

**Conclusion:** The only operation that requires Decodo is placing new orders on Polymarket. All reads, all on-chain operations, and all redemptions work without it.

---

## 2. Bundle redemption mechanism

### How redemption works

Polymarket token redemption is an on-chain transaction on Polygon, not a CLOB API call. The PM Bot `_auto_redeem` method:

1. Connects to Polygon RPC (`polygon-bor-rpc.publicnode.com`) -- no proxy needed, no geoblock
2. Queries Gamma API (GET) to check if market resolved -- no proxy needed
3. Checks `balanceOf(wallet, token_id)` on the CTF contract (`0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`)
4. Calls `redeemPositions(collateralToken, parentCollectionId, conditionId, indexSets[])` on the CTF contract
5. Signs the transaction with the wallet private key
6. Broadcasts to Polygon RPC -- no proxy needed

### Does redemption require Decodo?

**No.** Redemption is entirely on-chain. It requires:

- Polygon RPC access (works from SG, tested)
- The wallet private key (currently in `/root/.env.polymarket_keys.DISABLED`)
- ~0.01 MATIC for gas per redemption tx (~$0.005 at current prices)

### Can redemption be done manually?

Yes, three options:

1. **Polymarket UI** -- Connect wallet via MetaMask/Rabby from any non-geoblocked IP (VPN, home connection). Click "Redeem" on resolved markets. Zero code required.
2. **Standalone redemption script** -- A Python script using web3.py that calls `redeemPositions` on the CTF contract. Does not need py-clob-client, does not need the CLOB API, does not need Decodo. Can run from the SG server directly.
3. **Restart PM Bot temporarily** -- Re-enable `POLYMARKET_PRIVATE_KEY` in `.env`, start service, let `_auto_redeem` loop process all resolved positions, then stop service and re-disable key. Auto-redeem does NOT need the proxy.

---

## 3. Cost comparison

| Option | Monthly Cost | Total Cost Through Jul 31 | Notes |
|--------|-------------|---------------------------|-------|
| Keep Decodo | $85/mo | $255 (3 months) | Only value: ability to place new orders (permanently disabled) |
| Cancel today | $0 | $0 | All reads and redemptions work without it |
| Cheaper proxy (if ever needed) | $10-20/mo | $30-60 | Available on demand from BrightData, IPRoyal, etc. |

### Decodo value after freeze

| Capability | Needed? | Requires Decodo? |
|------------|---------|-----------------|
| Place new Polymarket orders | NO -- permanently disabled | Yes |
| Read market data / positions | Yes (monitoring) | No -- works direct from SG |
| Check resolution status | Yes (for redemption) | No -- Gamma GET works direct |
| Redeem resolved tokens | Yes | No -- on-chain via Polygon RPC |

**Decodo provides zero value after the freeze.** Every remaining operation works without it.

### Manual redemption cost

- Gas per redemption: ~0.01 MATIC (~$0.005)
- 141 active positions x $0.005 = ~$0.71 total gas
- Time: ~5 minutes per batch of ~20 positions via Polymarket UI
- Estimated total: 30-45 minutes over 6-24 months as positions resolve
- Total cost: less than $1 in gas + 45 minutes of time, versus $255+ for Decodo through July

---

## 4. Resolution timeline for 141 active positions

| Event | Est. Resolution | Positions | Est. Value |
|-------|----------------|-----------|------------|
| Eurovision 2026 | May 10-17, 2026 | ~20 | ~$37 |
| NBA Playoffs | May-June 2026 | ~3 | ~$13 |
| French Open | May 25 - Jun 8, 2026 | ~15 | ~$16 |
| India state elections | Mid-2026 | ~8 | ~$44 |
| West Ham relegation | May 25, 2026 | 1 | ~$28 |
| FIFA World Cup 2026 | Jun 11 - Jul 19, 2026 | ~25 | ~$83 |
| MegaETH FDV | Unknown | 1 | ~$36 |
| Other sports/events | Q2-Q3 2026 | ~25 | ~$50 |
| 2028 Dem nomination | 2027-2028 | ~35 | ~$64 |
| GTA VI / Jesus Christ | Unknown (years?) | 1 | ~$24 |

~75% of positions (by value) resolve by July 2026. The remaining ~25% (2028 Dem nomination + misc) will take 1-2 years. None of these require Decodo for redemption.

---

## 5. Recommendation: CANCEL TODAY

**Reasoning:**

1. Decodo is only needed for placing new Polymarket orders -- permanently disabled
2. All remaining operations (reads, resolution checks, on-chain redemption) work from Singapore without any proxy
3. $85/month for zero functional value
4. Even if we needed a proxy again (new strategy on Polymarket, hypothetically), cheaper alternatives ($10-20/month) are available on demand
5. Unredeemed winning positions are recoverable independently of Decodo

**Savings:** $85/month. If we would have kept it through July 31: $255 saved.

---

## 6. Cancellation procedure

**DO NOT EXECUTE -- review and confirm first.**

### Step 1: Confirm Decodo account

- Dashboard: https://dashboard.decodo.com (formerly smartproxy.com)
- Account: check email associated with payment (grep for receipt emails, or try the Polymarket username from the proxy URL)
- Proxy URL in .env: `http://Polymarket:***@nl.decodo.com:10001`
- The username "Polymarket" and password are in `/root/.env` (now commented out as `#FROZEN_2026-05-01 PROXY_URL=...`)

### Step 2: Check billing cycle

- Log into https://dashboard.decodo.com
- Navigate to Billing / Subscription
- Note: current plan name, billing date, whether annual or monthly
- If annual with months remaining: check refund policy
- If monthly: cancellation takes effect at end of current billing cycle

### Step 3: Cancel subscription

- Dashboard > Subscription > Cancel
- Select "Cancel at end of billing period" (not immediate, to avoid losing remaining paid days)
- Confirm cancellation
- Save cancellation confirmation email/screenshot

### Step 4: Verify proxy stops working (after billing period ends)

```bash
PROXY=$(grep '#FROZEN.*PROXY_URL' /root/.env | sed 's/#FROZEN_2026-05-01 //' | cut -d= -f2-)
curl -s --proxy "$PROXY" -o /dev/null -w '%{http_code}' "https://clob.polymarket.com/markets?limit=1"
# Expected: connection refused or 407 auth failed
```

### Step 5: Clean up .env

```bash
sed -i '/#FROZEN.*PROXY_URL/d' /root/.env
```

### Expected refund

- If monthly billing: $0 refund, subscription ends at cycle end
- If annual/prepaid: contact Decodo support for pro-rated refund
- No information available on billing cycle from server -- requires dashboard login

---

## 7. Signoff

**Date:** 2026-05-02
**Author:** Wasseem
**Decision:** CANCEL TODAY. Decodo provides zero value after the Polymarket order-placement freeze. All remaining operations (reads, resolution checks, on-chain redemption) work from Singapore without proxy. Savings: $85/month.


## Execution log
- 2026-05-02: Subscription cancelled by Wasseem via Decodo dashboard
- Billing end date: [paste from your cancellation confirmation]
- Refund: [amount, or "none -- monthly billing, runs to end of cycle"]
- Confirmation reference: [email subject or screenshot path]
- Status: cancelled, account dormant (not deleted, in case re-subscription ever needed)

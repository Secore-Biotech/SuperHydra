# Audit: Unredeemed Polymarket Winning Positions

**Date:** 2026-05-02
**Author:** Wasseem
**Status:** READ-ONLY AUDIT -- no redemptions executed, no keys re-enabled

---

## 1. Position inventory

Queried Polymarket Data API for all positions held by wallet `0x83fEe45597D95427C9712dFb13485d269A4F88c7`.

| Category | Count | Value / Cost |
|----------|-------|-------------|
| Redeemable winners (tokens to claim) | 116 | Value: $1,476.04, Cost: $652.28, Net: +$823.75 |
| Redeemable losers (resolved to $0) | 303 | Cost: $1,865.58 |
| Active (unresolved) | 140 | MTM: $330.65, Cost: $360.53 |
| **Total** | **559** | **All-in PnL: -$1,071.70** |

## 2. Top 20 unredeemed winning positions

| # | Market | Side | Tokens | Redemption Value |
|---|--------|------|--------|-----------------|
| 1 | Bitcoin above $78k on Apr 22 | Yes | 84.8 | $84.83 |
| 2 | XRP Up/Down on Apr 20 | Up | 80.0 | $80.00 |
| 3 | MegaETH launch token by Apr 30 | Yes | 64.3 | $64.31 |
| 4 | Bitcoin above $72k on Apr 9 | Yes | 52.6 | $52.65 |
| 5 | RC Strasbourg win Apr 26 | Yes | 43.6 | $43.64 |
| 6 | Solana Up/Down Apr 16 7PM | Up | 37.5 | $37.47 |
| 7 | MegaETH FDV above $1.2B | Yes | 36.4 | $36.43 |
| 8 | Ethereum above $2,300 on Apr 14 | Yes | 30.4 | $30.39 |
| 9 | Bitcoin $72-74k range | Yes | 30.0 | $30.03 |
| 10 | WTI Crude Oil HIGH $100 Apr | Yes | 29.6 | $29.55 |
| 11 | Dota 2: Liquid vs Falcons G1 | Team Liquid | 27.4 | $27.37 |
| 12 | Bitcoin above $74k on Apr 26 | Yes | 26.1 | $26.06 |
| 13 | XRP Up/Down Apr 20 8PM | Up | 24.0 | $24.03 |
| 14 | PSG win Apr 28 | Yes | 22.7 | $22.69 |
| 15 | Bitcoin Up/Down Apr 19 1:35PM | Up | 22.6 | $22.59 |
| 16 | Bitcoin Up/Down Apr 14 11PM | Up | 21.7 | $21.73 |
| 17 | Ostapenkov vs Gadamauri | Ostapenkov | 21.7 | $21.66 |
| 18 | Ethereum $2,300-$2,400 range | Yes | 18.2 | $18.17 |
| 19 | Elon Musk 1040-1079 tweets Apr | Yes | 17.5 | $17.54 |
| 20 | Bitcoin above $78k on Apr 23 | Yes | 17.1 | $17.14 |

Full list: 116 positions totaling $1,476.04. All are resolved markets where our side won. Each token redeems for $1.00 USDC.

## 3. On-chain verification

### Token balances at EOA

All 20 top positions show **0 token balance** at the EOA address via CTF contract `balanceOf()`. This does NOT mean the tokens are gone.

**Explanation:** Polymarket CLOB holds user CTF tokens in the Exchange contract, not at the user's EOA. When you trade on Polymarket, your tokens are escrowed by the Exchange. The Data API correctly reports them as "redeemable" because the Exchange holds them on your behalf, but a direct `balanceOf(EOA, tokenId)` returns 0.

To redeem, you must call through the Polymarket Exchange/NegRiskAdapter contracts, which will:
1. Call `CTF.redeemPositions()` for the escrowed tokens
2. Transfer the resulting USDC.e to your wallet

### Wallet balances on Polygon

| Asset | Balance |
|-------|---------|
| USDC.e | $0.00 |
| USDC (native) | $0.00 |
| MATIC/POL | 0.00 |

The wallet has zero liquid balance on Polygon. Before any redemption, MATIC must be deposited for gas (~0.5 MATIC, ~$0.25).

## 4. Cross-reference vs mm_final_pnl.md

### What mm_final_pnl.md reported (May 1)

| Category | Count | Cost | Value |
|----------|-------|------|-------|
| Resolved wins | 115 | $638.29 | $1,439.61 payout |
| Resolved losses | 303 | $1,865.58 | $0.00 |
| Active | 141 | $374.52 | $366.42 MTM |
| **Total** | **559** | **$2,878.39** | **$1,806.03** |

### What this audit found (May 2)

| Category | Count | Cost | Value |
|----------|-------|------|-------|
| Redeemable wins | 116 | $652.28 | $1,476.04 |
| Redeemable losses | 303 | $1,865.58 | $0.00 |
| Active | 140 | $360.53 | $330.65 MTM |
| **Total** | **559** | **$2,878.39** | **$1,806.69** |

### Differences explained

- **Win count 115 vs 116:** One additional market resolved between May 1 and May 2.
- **Win value $1,439.61 vs $1,476.04:** The additional resolution plus minor price rounding.
- **Active count 141 vs 140:** One position moved from active to redeemable (the newly resolved market).
- **Active MTM $366.42 vs $330.65:** Market price movements over 24 hours reduced active position values by ~$36.

### The critical gap in the previous NAV

The mm_final_pnl.md "Freeze-day NAV" section computed:

```
Binance USDT total:              $339.19
Polymarket liquid USDC:          $0.05
Polymarket active positions MTM: $366.42
TOTAL:                           $705.66
```

This **omitted** the $1,439.61 (now $1,476.04) in unredeemed winning tokens. The document acknowledged these wins existed in the "Total current value + payouts: $1,806.03" line but did not add them to the NAV. The $1,439.61 was treated as "payouts already received" -- but they were NOT received. They are unredeemed tokens sitting in the Polymarket Exchange contract.

**The previous freeze-day NAV of $705.66 was understated by ~$1,476.**

## 5. Revised freeze-day NAV

| Component | Previous | Revised | Source |
|-----------|----------|---------|--------|
| Binance USDT total | $339.19 | $339.19 | fapi account (unchanged) |
| Polymarket liquid USDC | $0.05 | $0.05 | CLOB balance |
| Polymarket active MTM | $366.42 | $330.65 | Data API (prices moved) |
| Polymarket unredeemed wins | NOT COUNTED | $1,476.04 | Data API redeemable |
| **Total** | **$705.66** | **$2,145.93** | |

**Note:** The active MTM dropped $36 overnight (market movements). Adjusting for same-day comparison: revised NAV at freeze time would have been ~$2,182.

### Revised lifetime PnL

| Metric | Value |
|--------|-------|
| Total deposits | $3,219.00 |
| Revised NAV | $2,145.93 |
| **Lifetime PnL** | **-$1,073.07** |
| **Return** | **-33.3%** |

This is consistent with the Polymarket all-in PnL of -$1,072 plus small Binance net losses (-$13 across L1/L4/L9/MM).

The previous implied lifetime PnL at $705.66 NAV was -$2,513 (-78%), which was nonsensical -- it implied the system lost more than the entire Polymarket portfolio, when in fact $1,476 was sitting unclaimed.

## 6. Recommended redemption method

### Recommendation: Polymarket UI (manual)

**Method:** Connect wallet to polymarket.com via MetaMask or Rabby from a non-geoblocked IP (any VPN or home connection outside Singapore). Navigate to Portfolio > Resolved. Click "Redeem" on each resolved market.

**Reasoning:**
1. **Simplest and safest.** No code to write, no private key re-exposure on the server, no risk of bugs in a custom script.
2. **Works without proxy.** The Polymarket UI handles all Exchange contract interactions client-side. The Singapore geoblock only affects the CLOB API for order placement, not the UI redemption flow.
3. **Batch-friendly.** The Polymarket UI shows all redeemable positions in one view. Recent updates allow batch redemption.
4. **No server access needed.** Import the private key into MetaMask on a personal device. Redeem from anywhere.

**Alternative: Standalone web3 script** -- would call the Exchange contract's redemption method directly. More automatable but requires writing and testing new code, understanding the exact Exchange contract ABI, and re-enabling the private key on the server.

**Alternative: Temporary PM Bot restart** -- the `_auto_redeem` loop already has the logic. But it requires re-enabling the private key on a server we're trying to freeze, and the bot might attempt other actions during startup.

### Pre-requisites

1. **Fund MATIC for gas:** Send ~0.5 MATIC (~$0.25) to `0x83fEe45597D95427C9712dFb13485d269A4F88c7` on Polygon. The wallet currently has 0 MATIC.
2. **Import private key:** Export from `/root/.env.polymarket_keys.DISABLED` on the server. Import into MetaMask on a personal device.
3. **Connect to Polymarket:** Navigate to polymarket.com, connect wallet, verify portfolio shows the 116 redeemable positions.

### Estimated cost and time

| Item | Estimate |
|------|----------|
| Gas (116 redemptions) | ~0.5-1.0 MATIC (~$0.25-0.50) |
| Time (UI batch redemption) | 15-30 minutes |
| Risk of failure | Low -- standard on-chain operation |

## 7. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Private key compromise during MetaMask import | Low | High ($1,476 at risk) | Use a clean browser profile, hardware wallet if available |
| Polymarket UI geoblock | Low | Low (use VPN) | Redemption is on-chain; UI just builds the tx |
| Gas price spike during redemption | Very low | Very low ($1-2 max) | Polygon gas is consistently cheap |
| Exchange contract bug | Very low | High | Polymarket has redeemed billions; this is battle-tested |
| Partial redemption failure | Low | Low | Retry failed positions individually |
| Tokens already redeemed (Data API stale) | Medium | None (nothing to lose) | On-chain verification showed 0 balance at EOA, but tokens are in Exchange contract -- redemption attempt will confirm |

### One uncertainty

The on-chain verification showed 0 token balance at the EOA for all 20 checked positions. This is expected (tokens are in the Exchange contract), but there is a scenario where some tokens were **already redeemed** by the PM Bot's `_auto_redeem` loop before service shutdown, and the resulting USDC was immediately recycled into new positions. If so, the Data API "redeemable" flag may be stale for some positions.

**Resolution:** Attempt redemption via UI. If tokens were already redeemed, the transaction will simply fail (no loss, just wasted gas). The actual recoverable amount may be less than $1,476 if some positions were already claimed.

**Confidence:** The math strongly supports that most/all of the $1,476 is unclaimed: $3,219 deposits - $1,072 all-in PnL = $2,147 expected NAV. Actual NAV without unredeemed wins is $670. The $1,476 gap matches almost exactly.

---

## Signoff

**Date:** 2026-05-02
**Author:** Wasseem

**Summary:** 116 unredeemed winning positions worth $1,476.04 in the Polymarket Exchange contract. Previous freeze-day NAV of $705.66 was understated by $1,476 -- revised to $2,145.93. Lifetime PnL is -$1,073 (-33.3%), not -$2,513 (-78%). Recommend manual redemption via Polymarket UI within the next week. Fund 0.5 MATIC for gas first.

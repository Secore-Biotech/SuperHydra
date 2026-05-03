# MM & Polymarket Wallet Final Accounting

**Date:** 2026-05-01  
**Wallet:** 0x83fEe45597D95427C9712dFb13485d269A4F88c7  
**Author:** Wasseem  

---

## Critical discovery: scope was wrong

The freeze plan estimated "17 unmatched LONG YES positions, $48–51 in MM inventory." The actual wallet contains **559 positions** across both the Market Maker and PM Bot, because both bots trade from the **same wallet** using the same private key (`POLYMARKET_PRIVATE_KEY`). The `MM_PRIVATE_KEY` in `.env` derives to a different address (`0x69F1...49F5`) and is unused by either bot.

Token-level overlap between the two bots is minimal (1 of ~580 token IDs), but clean PnL attribution is impossible for ~249 positions in crypto up/down and price markets where both bots were active.

---

## Wallet-level accounting (source of truth: Polymarket Data API)

| Category | Positions | Cost Basis | Current Value | PnL |
|----------|-----------|-----------|---------------|-----|
| Active (unresolved) | 141 | $374.52 | $366.42 (MTM) | -$8.10 |
| Resolved — LOST | 303 | $1,865.58 | $0.00 | -$1,865.58 |
| Resolved — WON | 115 | $638.29 | $1,439.61 (paid out) | +$801.32 |
| **Total** | **559** | **$2,878.39** | **$1,806.03** | **-$1,072.36** |

**Liquid USDC in wallet: $0.05**

### What the numbers mean

- **$2,878.39 total cost basis** does not mean $2,878 was deposited. Winning payouts ($1,439.61) were recycled into new positions. Actual capital deployed from external sources is lower.
- **-$1,072.36 all-in PnL** is the net loss across all Polymarket activity since the wallet was created.
- **$366.42 active MTM** is the mark-to-market value of 141 unresolved binary positions at current market prices. Actual resolution value will be $0 (all lose) to $4,000+ (all win at $1/token face value), but MTM is the best available estimate.

---

## Top 20 active positions (by current value)

| # | Position | Outcome | Size | Avg Price | Cost | MTM | Strategy |
|---|----------|---------|------|-----------|------|-----|----------|
| 1 | MegaETH FDV above $1.2B on launch? | YES | 36.4 | $0.384 | $14.00 | $36.41 | MM |
| 2 | Will West Ham be relegated? | YES | 81.3 | $0.445 | $36.22 | $28.06 | MM |
| 3 | Will Jesus Christ return before GTA VI? | NO | 46.2 | $0.520 | $24.00 | $23.77 | MM |
| 4 | DMK wins most seats in 2026 W. Bengal? | YES | 11.2 | $0.719 | $8.05 | $9.69 | MM |
| 5 | NBA Playoffs: 76ers vs Celtics | 76ers | 33.3 | $0.090 | $3.00 | $9.65 | MM |
| 6 | BJP wins most seats 2026 W. Bengal? | YES | 18.2 | $0.494 | $9.00 | $8.73 | MM |
| 7 | IUML wins 16–18 seats Kerala? | YES | 24.2 | $0.319 | $7.71 | $8.16 | MM |
| 8 | AITC wins most seats W. Bengal? | YES | 14.1 | $0.425 | $6.00 | $7.44 | MM |
| 9 | Will Greece win Eurovision 2026? | YES | 36.4 | $0.055 | $2.00 | $6.30 | PM:BUNDLE |
| 10 | Will Spain win 2026 FIFA World Cup? | YES | 32.7 | $0.156 | $5.10 | $4.99 | PM:BUNDLE |
| 11 | Will France win 2026 FIFA World Cup? | YES | 27.9 | $0.145 | $4.05 | $4.59 | PM:BUNDLE |
| 12 | Will Switzerland win 2026 FIFA WC? | YES | 463.6 | $0.011 | $5.10 | $4.40 | PM:BUNDLE |
| 13 | Will Canada win 2026 FIFA WC? | YES | 675.0 | $0.006 | $4.05 | $4.39 | PM:BUNDLE |
| 14 | Will Portugal win 2026 FIFA WC? | YES | 58.5 | $0.069 | $4.05 | $4.30 | PM:BUNDLE |
| 15 | Will USA win 2026 FIFA World Cup? | YES | 270.0 | $0.015 | $4.05 | $4.18 | PM:BUNDLE |
| 16 | Will Europe win 2026 FIFA WC? | YES | 5.6 | $0.720 | $4.00 | $4.03 | PM:BUNDLE |
| 17 | Will Brazil win 2026 FIFA WC? | YES | 47.1 | $0.086 | $4.05 | $4.03 | PM:BUNDLE |
| 18 | Will Netherlands win 2026 FIFA WC? | YES | 120.0 | $0.034 | $4.05 | $4.02 | PM:BUNDLE |
| 19 | XRP dip to $0.40 by Dec 31 2026? | YES | 25.9 | $0.270 | $7.00 | $4.01 | SHARED |
| 20 | Will England win 2026 FIFA WC? | YES | 35.5 | $0.114 | $4.05 | $3.93 | PM:BUNDLE |

---

## Top 15 resolved losses

| # | Position | Size | Avg Price | Loss | Strategy |
|---|----------|------|-----------|------|----------|
| 1 | BTC Up/Down 5m Mar 18 6:30AM | 8,928.6 | $0.024 | -$209.89 | SHARED |
| 2 | ETH above 2,430 Apr 16 9PM | 1,680.1 | $0.063 | -$106.67 | SHARED |
| 3 | BTC Up/Down 5m Mar 18 3:15AM | 377.3 | $0.106 | -$39.91 | SHARED |
| 4 | ETH Up/Down Apr 22 4PM | 105.2 | $0.357 | -$37.58 | SHARED |
| 5 | ETH Up/Down 15m Apr 22 3PM | 379.4 | $0.098 | -$37.31 | SHARED |
| 6 | ETH Up/Down 15m Apr 22 4:15AM | 326.5 | $0.096 | -$31.37 | SHARED |
| 7 | Arvell Reese 2nd pick NFL draft | 45.9 | $0.562 | -$25.77 | MM |
| 8 | ETH Up/Down 15m Apr 9 8:30AM | 142.8 | $0.180 | -$25.68 | SHARED |
| 9 | Gadamauri vs Broom (boxing) | 219.5 | $0.113 | -$24.90 | MM |
| 10 | Dodgers vs Giants | 307.4 | $0.081 | -$24.83 | MM |
| 11 | ETH above 2,380 Apr 17 3AM | 205.1 | $0.111 | -$22.80 | SHARED |
| 12 | BTC Up/Down Apr 16 6:30PM | 46.4 | $0.482 | -$22.38 | SHARED |
| 13 | BTC above 76,800 Apr 17 12AM | 132.3 | $0.147 | -$19.44 | SHARED |
| 14 | XRP Up/Down Apr 16 5PM | 28.1 | $0.652 | -$18.32 | SHARED |
| 15 | Bouzas Maneiro vs Shnaider (tennis) | 25.8 | $0.670 | -$17.26 | MM |

**Pattern:** The largest losses are concentrated in short-duration crypto Up/Down markets (5-min, 15-min, hourly). These are effectively coin-flip bets with negative edge (Polymarket takes a fee). The $209.89 BTC 5-minute bet alone accounts for 11% of total losses.

---

## Approximate strategy attribution

Clean separation is possible for ~310 of 559 positions. The remaining ~249 (crypto up/down, price, range markets) were traded by both bots through the same wallet.

| Strategy | Est. Positions | Cost Basis | Resolved Losses | Current MTM | Est. PnL |
|----------|---------------|-----------|-----------------|-------------|----------|
| PM Bot: BUNDLE_ARB | ~159 | ~$230 | ~$47 | ~$238 | ~-$39 |
| PM Bot: BOND | ~5 | ~$24 | ~$6 | ~$30 | ~$0 |
| PM Bot: FEAR_FADE | ~3 | ~$9 | $0 | ~$9 | ~$0 |
| MM: Sports/Esports/Events | ~87 | ~$311 | ~$388 | ~$106 | ~-$593 |
| SHARED: Crypto markets | ~249 | ~$427 | ~$1,391 | ~$20 | ~-$440* |
| Other | ~56 | ~$1,877 | ~$34 | ~$0 | ~$0* |
| **Total** | **559** | **$2,878** | **$1,866** | **$366** | **-$1,072** |

*The SHARED crypto bucket is where the overwhelming majority of losses occurred. Both the MM's market-making on crypto Up/Down markets and the PM Bot's directional FEAR_FADE and NORMAL_LAG trades contributed to this $1,391 in resolved losses.

---

## The real MM picture

The Market Maker was **not** a market-neutral spread capturer. The audit reveals:

1. **10 completed roundtrips** earned $3.63 in realized spreads (confirmed from SPREAD_CAPTURED logs)
2. **Hundreds of one-sided fills** accumulated directional inventory — the 4.2:1 buy:sell ratio from the postmortem understated the problem
3. **Short-duration crypto markets** (5-min, 15-min Up/Down) were the primary venue — these are effectively binary bets that resolve in minutes, not traditional market-making venues
4. **$1,391+ in resolved losses** on crypto markets where both MM and PM Bot operated, with no hedging or inventory management

The MM's true PnL is not +$3.63 (spreads only), not -$48 (original inventory estimate), but somewhere in the -$400 to -$600 range when including all resolved losses on markets where it was the primary or sole actor.

---

## Corrected realized cash settlement

### Already settled (resolved positions)

| Outcome | Cost Basis | Cash Received | Net |
|---------|-----------|---------------|-----|
| Won (115 positions) | $638.29 | $1,439.61 | +$801.32 |
| Lost (303 positions) | $1,865.58 | $0.00 | -$1,865.58 |
| **Subtotal resolved** | **$2,503.87** | **$1,439.61** | **-$1,064.26** |

### Still open (active positions)

| Category | Count | Cost Basis | Current MTM |
|----------|-------|-----------|-------------|
| FIFA World Cup 2026 | ~25 | ~$87 | ~$83 |
| 2028 Dem Nomination | ~44 | ~$64 | ~$64 |
| Eurovision 2026 | ~19 | ~$38 | ~$37 |
| Indian State Elections | ~8 | ~$46 | ~$44 |
| Sports (West Ham, NBA, etc.) | ~10 | ~$55 | ~$52 |
| MegaETH FDV | 1 | $14 | $36 |
| Jesus Christ vs GTA VI | 1 | $24 | $24 |
| Other | ~33 | ~$47 | ~$27 |
| **Subtotal active** | **141** | **$374.52** | **$366.42** |

### True all-in MM PnL

Precise MM-only PnL is not computable because the wallet is shared. The wallet-level all-in PnL is the authoritative number:

| Component | Amount |
|-----------|--------|
| Total capital deployed (cost basis) | $2,878.39 |
| Cash received from winning resolutions | $1,439.61 |
| Current MTM of active positions | $366.42 |
| Liquid USDC | $0.05 |
| **Total recoverable** | **$1,806.08** |
| **All-in PnL** | **-$1,072.31** |

The 10 MM roundtrip spreads ($3.63) are a rounding error against $1,072 in total wallet losses.

---

## Updated freeze-day NAV (point estimate)

| Component | Value | Source |
|-----------|-------|--------|
| Binance Futures USDT | $339.19 | fapi account query, post-L9 close |
| ↳ Free | $290.09 | |
| ↳ Used (L4 + L1 margin) | $49.10 | |
| ↳ L4 uPnL (LINK + ADA) | -$0.86 | |
| ↳ L1 uPnL (APT) | -$0.93 | |
| Polymarket liquid USDC | $0.05 | MM log balance |
| Polymarket active positions (MTM) | $366.42 | Data API, 141 positions |
| **Freeze-day NAV** | **$705.66** | |

### Previous vs corrected

| | Previous estimate | Corrected |
|---|---|---|
| Binance | $339.19 | $339.19 (unchanged) |
| Polymarket USDC | $0.05 | $0.05 |
| PM Bot positions | $241.40 (trades.db cost basis) | — |
| MM inventory | $48–51 (guess) | — |
| Polymarket positions (combined) | $289–292 | $366.42 (MTM, Data API) |
| **Total** | **$628–681** | **$705.66** |

The previous range was wrong in both directions:
- **Understated** the Polymarket position value (Data API MTM > trades.db cost basis + MM guess)
- **Conceptually wrong** by treating trades.db as source of truth instead of on-chain state

### Confidence and resolution range

The $366.42 Polymarket MTM is based on current market prices for 141 binary outcomes. The resolution range:

| Scenario | Polymarket Value | Total NAV |
|----------|-----------------|-----------|
| All active positions lose | $0.00 | $339.24 |
| Current MTM holds | $366.42 | $705.66 |
| High upside (some longshots hit) | ~$500 | ~$839 |

**Best estimate for planning: $705.66.** Most active positions are in events that haven't resolved yet (FIFA WC June–July 2026, Eurovision May 2026, Indian elections 2026, 2028 Dem nomination). The MTM will fluctuate until resolution.

---

## Signoff

**Date:** 2026-05-01  
**Author:** Wasseem  

**The uncomfortable number:** This wallet has lost $1,072 on Polymarket. The MM contributed $3.63 in spreads and an unknown but large share of $1,866 in resolved losses. The PM Bot's bundle arbitrage positions are roughly break-even. The catastrophic losses came from short-duration crypto binary bets — a venue where market-making is indistinguishable from gambling.

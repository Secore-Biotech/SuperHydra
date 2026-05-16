# Sleeve B Candidate #2 — Stage A Phase 1 data inventory

**Status:** Phase 1 recon only — not a Stage A verdict, not governance-binding
**Subordinate to:** `docs/strategies/sleeve_b_quality_preregistration.md` (commit `4d307e6`)
**Phase 1 budget:** ≤ 2 calendar days of the 10-day Stage A budget
**Date opened:** 2026-05-16

---

## 0. Scope and classification

This document is a **Phase 1 recon snapshot** of data-access state for the fee-yield quality candidate. It is not governance and not anti-cherry-pick-binding. If access state changes during Stage A (e.g., a Token Terminal subscription is acquired mid-window), this document is updated; the master pre-registration at commit `4d307e6` is not.

Phase 1 produces a single decision at §5:

- **Sufficient access exists** → proceed to Phase 2 (eligible-universe construction)
- **Insufficient access, acquirable** → list acquisition steps, decide whether budget permits
- **Insufficient access, blocking** → shelve at Phase 1 with kill action document

Phase 1 does not score sub-gates A1–A5. It establishes whether scoring is feasible at all.

---

## 1. Token Terminal access audit

**Operator-confirmed state:** Q1 = (a). No subscription. No API key. Public-facing data only.

**Implication:** Token Terminal cannot be used as a Stage A primary source. Public web data is not point-in-time-grade and is rate-limited. Specifically:

- No programmatic historical pull of protocol fees across the frozen top-30
- No exposure of publication / as-of timestamps via the public interface
- No SLA on coverage for the 2023-04-15 → 2026-04-15 OOS window
- Manual scraping is both prohibited by ToS and incompatible with PIT discipline

**Consequence for Stage A — A3 reformulation (locked):**

A3 as originally specified in the pre-registration envisioned **agreement between two independently maintained aggregation layers** (Token Terminal and DeFiLlama). Due to lack of Token Terminal access, A3 is reformulated as:

> **DeFiLlama versus direct on-chain reconstruction on a pre-locked spot-check subset.**

This is a **candidate-specific forced substitution caused by unavailable TT access, not a relaxation of A3.** It is locked at this point in Phase 1 and does not represent dynamic flexibility or an evolving interpretation. Once committed in this inventory, the reformulation is fixed for the entire remainder of Stage A and Stage B. No future "maybe use another source instead."

**Asymmetry disclosure (mandatory):**

The original A3 pair (TT vs DeFiLlama) compares two commercial aggregators with independent methodologies. The reformulated A3 pair (DeFiLlama vs on-chain reconstruction) compares **aggregator versus reconstructed truth**. These are not the same class of comparison:

- **Methodologically stricter:** on-chain reconstruction is closer to ground truth than any aggregator
- **Coverage-weaker:** reconstruction is feasible only on the spot-check subset (3 names), not across the eligible universe
- **Failure-mode different:** disagreement now means aggregator is wrong, not that two aggregators interpret differently

The A3 thresholds (<0.6 FAIL, 0.6–0.7 PASS_WARNING, ≥0.7 PASS_CLEAN) from the pre-registration are preserved without modification.

**Spot-check subset (pre-locked, before Phase 2 begins):**

| Asset | Justification |
|---|---|
| ETH | EIP-1559 fee burn + tips; clean mechanism across the full OOS window; archive nodes and Etherscan-class APIs reliable |
| SOL | Validator priority fees; mechanism well-documented; reconstruction via public RPC feasible |
| AVAX | C-chain fees; stable mechanic across the OOS window; explorer APIs reliable |

**BNB excluded from spot-check:** BNB Chain fee mechanics involve validator-share dynamics that complicate clean reconstruction. Kept out to maintain auditability of the spot-check subset.

**Why these three, locked now:** The spot-check names are locked **before** running any DeFiLlama-vs-on-chain comparison. This prevents the failure mode where a name is added or dropped after observing disagreement, which would be a cherry-pick. Lock-before-look discipline applies.

**Acquisition option (not pursued in Phase 1):** Token Terminal Pro / API tier exists at a non-trivial monthly cost. Acquisition would restore the original A3 pair (aggregator-vs-aggregator) but consumes Sleeve B budget on subscription rather than research. Deferred to verdict §5.

---

## 2. DeFiLlama access audit

**Initial state:** Public API endpoints documented at https://api.llama.fi and https://api.llama.fi/protocols. No subscription required for read access.

**Phase 1 sub-tasks (to be executed before §5 verdict):**

### 2.1 Endpoint inventory for protocol fees

DeFiLlama exposes:
- `/protocols` — protocol metadata, current TVL, current fees-24h / fees-7d / fees-30d snapshots
- `/summary/fees/{protocol}` — historical daily fee series per protocol
- `/overview/fees` — aggregated fee data across protocols

Phase 1 must verify:
- Historical depth for each protocol in the top-30 universe across the OOS window
- Daily-resolution availability (weekly resolution is the minimum needed; daily is preferred)
- Whether each top-30 asset has a clean protocol mapping (token symbol → protocol slug)
- Endpoint stability and rate limits in practice

### 2.2 PIT vs backfill state — **the critical question**

DeFiLlama's API returns current best-known values. The question is whether:

- (a) Historical values are immutable once published (PIT-clean), or
- (b) Historical values are revised retrospectively when methodology changes or new protocols are added (backfilled, contaminated)

Verification approach in Phase 1:
- Check DeFiLlama documentation / blog for stated methodology revisions
- Check DeFiLlama's GitHub (DefiLlama-Adapters repo) for adapter change history — adapter changes mid-window are evidence of backfill
- Compare DeFiLlama snapshots from public archives (Wayback Machine snapshots of `defillama.com/fees`) against current API values for matching dates, on 3–5 protocols

If snapshot values disagree with current API values for the same historical date, DeFiLlama is backfilled and A4 PIT discipline is at risk.

### 2.3 Symbol-to-protocol mapping for the top-30 universe

The top-30 USDT-perp universe is composed of token tickers (BTC, ETH, SOL, etc.). DeFiLlama indexes protocols, not tokens. Mapping required:

- One-to-one: ETH → Ethereum chain fees, BNB → BNB Chain fees
- One-to-many: SOL → Solana chain fees + Jito + Marinade + ... (which is the "fee" for SOL the token?)
- Many-to-none: DOGE, SHIB, PEPE, WIF — memecoins with no protocol-fee analog → excluded from eligible universe per §2 of the pre-registration (excluded-names report)
- Ambiguous: LDO (Lido governance) vs Lido protocol fees — operator-locked decision needed

Mapping must be locked as part of the canonical taxonomy (A5).

---

## 3. On-chain spot-check feasibility

Spot-check subset is **pre-locked in §1** (ETH, SOL, AVAX) per the A3 reformulation. This section documents reconstruction feasibility for context; it does not propose alternatives.

| Asset | On-chain fee reconstruction | Feasibility | Status |
|---|---|---|---|
| ETH | Block fee burn + tips, indexable via Etherscan API or archive node | High | **Locked spot-check** |
| SOL | Validator priority fees, indexable via public RPC | Medium | **Locked spot-check** |
| AVAX | C-chain fees via Snowtrace / archive | High | **Locked spot-check** |
| BNB | BNB Chain fees via BscScan | High | Excluded — validator-share dynamics complicate clean reconstruction |
| MATIC / POL | Polygon PoS fees | Medium | Excluded — rebrand mid-window |
| ARB | Arbitrum sequencer fees | Medium | Excluded — sequencer revenue mechanic complexity |
| OP | Optimism sequencer fees | Medium | Excluded — similar to ARB |

**SOL note (medium feasibility, included anyway):** SOL priority-fee mechanics evolved during the OOS window. Reconstruction is feasible but requires per-epoch awareness of fee-market rules. The methodological rigor of including SOL (a top-3 universe asset) outweighs the reconstruction complexity. If SOL reconstruction proves operationally infeasible in Phase 2, the inventory document is updated to drop SOL and the §1 lock is revisited as a one-time correction — this is the only condition under which the spot-check set may change after Phase 1.

Tooling state: no existing on-chain reconstruction infrastructure in the repo (confirmed §4). Phase 2 would build minimal API-based pulls (Etherscan-class APIs, public RPCs).

---

## 4. Existing local cache audit

**Server check (167.71.196.165):** Skipped. SSH key auth to the production server is currently unavailable from this Mac (ed25519 key not present, RSA key not configured for the server, SSH key debugging is unrelated to Sleeve B). Rationale for proceeding without it: production server runs legacy strategies only (MM, L9, L4 V3, Polymarket) — none of which touch fee-yield data. Any fee-yield cache for new-program work would be in the local `hydra-next` repo, not the server. Risk accepted.

**Local repo check (`hydra-next` at commit `4d307e6`):**

Grep performed across `data/`, `artifacts/`, `research/`, `analytics/`, `strategies/`, `scripts/`, `tests/`, `docs/`:

```
grep -RilE "token terminal|tokenterminal|defillama|protocol fee|protocol_fees|fee yield|fee_yield" ...
→ no matches
```

Directory listings confirm:
- `data/vendors/` — empty
- `data/ingestion/vendors/` — contains only `binance/` (price and funding data, not fee data)
- `research/factors/` — empty
- `analytics/` — execution / microstructure (effective spread, slippage), not fee data
- `artifacts/` — SOL regime archives + cache directory, not fee data

**Conclusion:** No existing fee/revenue cache or vendor adapter found in the local repo. Fresh acquisition required for any fee data ingestion.

---

## 5. Phase 1 verdict

**Pending completion of §2.1, §2.2, §2.3.** This section is to be filled in once the DeFiLlama recon is executed.

**Dominant existential risk identified:** With Token Terminal off the table (Q1 = (a)), A4 (point-in-time discipline on DeFiLlama) is now the load-bearing gate for the entire candidate. The likely critical question for the whole of Stage A is:

> **Can DeFiLlama historical fee data be reconstructed point-in-time for the OOS window?**

If yes, Stage A continues to Phase 2 with A4 cleared. If no, Stage A fails at A4 before A1/A2/A3/A5 are computed. Sharpe, breadth, taxonomy — none of those matter if A4 cannot be cleared. Discovering this in Phase 1 (rather than after a backtest) is exactly why Stage A exists.

The verdict will take one of three forms:

### 5.A — Proceed

DeFiLlama historical fee data is verifiably PIT-clean (immutable historical values) OR reconstructable via Wayback / archive snapshots for ≥80% of rebalance-date eligible observations.

- Stage A proceeds to Phase 2 (eligible-universe construction)
- Reformulated A3 (DeFiLlama vs on-chain spot-check on ETH/SOL/AVAX) applies per §1 lock
- Token Terminal acquisition explicitly declined for the duration of candidate #2
- A4 expected outcome: PASS_CLEAN

### 5.B — Proceed with warning

DeFiLlama historical fee data is partially reconstructable — PIT discipline can be established for ≥80% of rebalance-date eligible observations via Wayback snapshots, but not full programmatic PIT timestamps.

- Stage A proceeds to Phase 2, but A4 will resolve to PASS_WARNING
- Stage B output classified as **non-decision-grade exploratory memo** per §4.B3 of the pre-registration
- Promotion to paper is structurally impossible regardless of Stage B Sharpe / drawdown
- The factor returns to research even on a strong Stage B result, pending proper PIT data ingestion
- Operator decision required at end of Phase 1: is exploratory-only Stage B worth the remaining ~30 days of Sleeve B budget, given the path-to-promotion is closed for this candidate cycle?
- Acceptable outcome if operator wants the research signal even without a promotion path
- Kill alternative if operator prefers to preserve budget for a future candidate

### 5.C — Kill

DeFiLlama historical fee data is backfilled with no reconstructable PIT path AND Token Terminal acquisition is declined.

- A4 (PIT discipline) is FAIL by construction — no PIT-grade source exists for the eligible universe
- Stage A verdict is FAIL via A4 before A1/A2/A3/A5 are computed
- Candidate #2 shelved at Phase 1
- Kill action document drafted at `docs/strategies/sleeve_b_quality_kill_action.md` per §5 of the pre-registration
- Kill mode classification: **metric-definition kill (data access)**, distinct from xs-momentum's construction-fragility kill and A2's signal-absence kill
- Remaining ~38 days of Sleeve B budget preserved for a future candidate

---

## 6. Phase 1 budget tracking

| Item | Budget | Consumed | Remaining |
|---|---|---|---|
| Phase 1 (recon) | 2 days | 0 (recon in progress) | 2 days |
| Stage A total | 10 days | 0 (Stage A clock from `4d307e6`, 2026-05-16 12:24:45 +0100) | 10 days |
| Candidate #2 total | 41 days | 0 | 41 days |

Phase 1 budget overrun (>2 days without §5 verdict) is itself a signal that PIT-grade data access for fee-yield is harder than the candidate can absorb within the Sleeve B budget. Overrun triggers operator review, not automatic kill.

---

## 7. Next steps

1. Execute §2.1 — DeFiLlama endpoint inventory and historical-depth verification
2. Execute §2.2 — DeFiLlama PIT verification (Wayback comparison on 3–5 protocols)
3. Execute §2.3 — Symbol-to-protocol mapping draft for the top-30 universe
4. Execute §3 — On-chain spot-check feasibility confirmed; tooling deferred to Phase 2 if Phase 1 verdict is 5.A
5. Update §5 with verdict
6. Commit this document with Phase 1 verdict, before any Phase 2 work begins

---

*Phase 1 recon document for Sleeve B candidate #2 — revenue-bearing quality (fee-yield). Subordinate to pre-registration at commit `4d307e6`. Not anti-cherry-pick-binding. Updates permitted as access state changes.*

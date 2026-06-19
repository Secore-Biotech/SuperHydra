# Token Unlock — Drift-Based Mispricing Trade: Pre-Registered POC Spec

**Status:** Locked BEFORE trial data is seen. This is a 1-year proof-of-concept spec, NOT a §3-compliant verdict (the Tokenomist free trial gives only 12 months backward; Risk Standard v1.0 §3 requires ≥24mo OOS, so the trial cannot produce a deployment verdict — only a "does the signal exist at all" read that decides whether paying for Elite-tier 2-year history is justified).
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Why pre-registered:** "expected realized impact" and the divergence rule must be fixed before seeing data, or the POC overfits to whatever makes the 1-year sample look tradeable. This is the immunization guard applied to the trade itself, same discipline that held every prior probe.

## What this POC tests

The standalone mispricing trade (Gate 3A: shape confirmed) in its **drift-based** form — the version that does NOT require point-in-time schedule-revision history (which the Tokenomist schema likely lacks; Gate 2A risk). It needs only: unlock event dates + sizes (Unlock Events endpoint), circulating supply (Daily Emission endpoint), and price series (free: Binance substrate or DeFiLlama free /chart).

**Hypothesis (unchanged from deep pre-screen):** a scheduled unlock's price impact is partly priced in via pre-event drift; realized impact diverges systematically from priced-in. Trade the divergence.

**Drift-based operationalization (the key move):** "priced-in impact" = the token's abnormal cumulative return in the pre-unlock window, measured against the token's own prior trajectory (NOT a benchmark — keeps it standalone). "Realized impact" = the token's return in the post-unlock window. The signal is whether pre-drift predicts/underprices post-move.

## Locked parameters (do not tune to the 1-year data)

- **Event universe:** unlock events with size ≥ 5% of circulating supply at event date (Risk Standard-consistent threshold, locked economically not to count). Cliff unlocks only for the POC (linear-start events deferred — cleaner signal first).
- **Circulating supply:** from Daily Emission endpoint, supply as of the event date (denominator for the 5% filter).
- **Pre-unlock (drift) window:** t-30d to t-1d before the unlock date. Abnormal drift = cumulative log return over this window, minus the token's own trailing-90d median 30d-return (de-trend against own history — the "vs own trajectory, no benchmark" definition).
- **Post-unlock (realization) window:** t+0 to t+5d. Realized impact = cumulative log return over this window.
- **Direction rule (conditional on divergence, NOT "always short"):**
  - If pre-drift is SMALL/positive (market hasn't priced the unlock) AND unlock is large → expect under-pricing → **short** at t-1, cover t+5.
  - If pre-drift is LARGE-negative (market has already sold the unlock hard) → expect over-pricing/relief → **long** at t-1, exit t+5.
  - Threshold separating "small" from "large" pre-drift: locked at the **median pre-drift across the sample** (computed once, not tuned). Above median negative = "priced in" (long candidate); below = "not priced" (short candidate).
- **Cost model:** Risk Standard realistic costs — assume altcoin round-trip 30bps (wider than BTC/ETH's 10bps; thin-name caveat), per-event. Flag any token whose ADV can't support a family-capital position as EXECUTION-SUSPECT (Gate 3 liquidity).

## POC pass/fail (NOT a deployment verdict — a "worth paying for Elite?" verdict)

This runs on ~12 months, ~50 trial tokens. It cannot clear §3. It answers only:

- **POC-POSITIVE:** abnormal pre-drift exists AND realized impact diverges from it in a direction the rule captures, with mean net > 0 across events after costs, on the 1-year sample. → Justifies paying for Elite-tier 2-year data to run the real §3 audit. NOT a deployment decision.
- **POC-NEGATIVE:** no abnormal drift, OR no divergence, OR negative net after costs on 1 year. → Do not pay for Elite. Token Unlocks closes as POC-failed (cheaply, on free trial). Discovery Program reaches terminal exhaustion.
- **POC-DATA-LIMITED:** too few ≥5% cliff events in 50 tokens × 1yr to read anything (the Section A sparsity risk at trial scale). → Inconclusive; the event-density question itself becomes the gate, and only full-universe Elite data could resolve it.

## Gate 2A note (settled in parallel, day 1)

Separately, day 1 confirms whether Unlock Events carries any revision/as-of-date field. If YES → the richer "announced-schedule-change" version becomes available later. If NO (expected) → only this drift-based version is viable, which is fine because it was designed to not need PIT history. Either way the POC proceeds on drift.

## Explicitly NOT in scope for the POC

- No §3 verdict (1yr < 24mo).
- No deployment, no capital, no signal-program spec.
- No parameter tuning on the trial data (thresholds locked above).
- No linear-unlock events (cliffs only for clean first read).

— end —

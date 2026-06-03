# Vol-Dislocation (Liquidity Recovery) — §4 Deployability Screen

**Status:** Provisional verdict — screen, not a spec. Reaches a provisional FAIL on §4 bullet 5 and ends on an operator decision. No probe, no code, no pre-registration.
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Subject:** The single survivor of the §6 same-object screen — *liquidity recovery / spread compression following a volatility shock* (`vol_dislocation_same_object_test.md`, `5cb046d`).
**Gate applied:** `edge_scoping.md §4`, especially **bullet 5** (deployment shape operationalisable under the program envelope: weekly time budget, $50k ceiling, no overnight/bespoke ops, no excluded infrastructure) and **bullet 4** (implementation footprint — no net-new institutional-grade infrastructure). Bullet 5 is, per §4's own note, "the one most often skipped," and it is the binding gate here.

---

## 1. The object, and what §4 asks of it

The §6 screen established that *post-shock microstructure recovery* (order-book depth reconstitution and bid-ask spread compression following a vol event) is a genuinely distinct measured object — not Section A's price-return object, not the funding cluster, not the basis cluster. That makes it a valid object to *measure*. §4 asks the next question: **does observing this object motivate a trade that is operationalisable under the program envelope?** A distinct measurable phenomenon with no deployable strategy is, in §4's own words, research entertainment — filtered before execution.

## 2. Bullet 5 — deployment shape (the binding gate)

What trade does "liquidity recovers after a shock" actually motivate? Four candidate shapes, each assessed:

| Shape | What it is | Why it fails / escapes the envelope |
|---|---|---|
| **A. Liquidity provision** | Post-shock spreads are wide; place limit orders inside them and capture the compression as the book heals | This *is* market-making. It is the legacy MM strategy's domain (frozen, behind the roadmap §7 firewall, out of new-program scope). Worse, it is the **A2 failure in another costume**: you provide liquidity exactly when execution is hardest — adverse selection peaks during stress (you fill because price is running through your quote), depth is thin, and venues rate-limit. A2 was shelved on precisely this "fires only when execution is hardest" logic. |
| **B. Execution-timing overlay** | Use "liquidity has recovered" as a green-light to execute *other* strategies' orders into healthy books rather than thin post-shock ones | Legitimate and probably genuinely useful — but it is an **execution-quality improvement, not a standalone alpha engine**. The family-capital search is for an engine, not an overlay on engines that don't yet exist. It cannot be the surviving direction; it could only be a refinement to a future one. |
| **C. Directional / convergence bet** | Bet that a price relationship normalizes as liquidity returns | "Price relationship normalizes" is basis or mean-reversion. This collapses straight back into the §3.1 basis kills, A2, and Section A clusters — **already dead**, on a different gate than §4. |
| **D. Volatility mean-reversion** | Trade the vol spike itself (spike → revert) | A vol-persistence cousin of Section A, and it requires options / vol instruments — a data and infrastructure class the substrate does not have. Out of object-scope (drifts toward Section A) and out of envelope (instruments). |

**Result:** every deployment shape for this object either reduces to market-making (excluded + structurally stress-hard), is an execution overlay (not an engine), or collapses into an already-killed cluster. No standalone, deployable, in-envelope strategy shape survives. **Provisional FAIL on §4 bullet 5.**

## 3. Secondary gates (moot if bullet 5 holds, recorded for completeness)

- **Bullet 4 — data precondition / footprint.** Measuring depth/spread recovery requires L1/L2 quote data (`bookTicker` for spread, `bookDepth` for depth). The known data substrate from the project record is Binance perp/spot **trades**, **funding**, and the **metrics archive** (OI, long/short ratios at 5-min). Quote/depth is a data class **not evidenced as ingested**. New ingestion would sit within the existing archive pattern (not institutional-grade, so not an automatic §4 bullet-4 fail), but it is real new work that only the maker/provision shape (A) would actually need — and shape A is already excluded. *(Substrate claim is from records; confirm before relying on it.)*
- **Bullet 1 — frequency.** §4 excludes microseconds-to-seconds. Spread compression is a seconds-to-minutes phenomenon; capturing it on the maker side is a seconds-scale execution game sitting on the excluded boundary. Depth recovery (minutes-to-hours) is within the frequency band, but the only shape that trades it (provision) needs fast fills regardless.

Neither secondary gate is reached if bullet 5 stands. They are recorded so the direction is not re-proposed later with "but we could get the depth data" — the data is not the binding constraint; the absence of a deployable shape is.

## 4. Provisional verdict

> **Vol-dislocation (liquidity recovery) — provisional FAIL (§4 bullet 5).** The object is a genuine §6 survivor but has no standalone, in-envelope deployment shape: every candidate shape is excluded (market-making), non-standalone (execution overlay), or already-killed (basis/mean-reversion/vol-persistence). The data precondition and frequency tension reinforce but are not the binding constraint.

This is provisional for one reason only: bullet 5 is a question about *intended deployment*, and intent is the operator's, not a fact in the records. If there is a deployable shape outside the four above, the verdict reopens.

## 5. Operator decision required

```
Is there a deployment shape for post-shock liquidity recovery
OUTSIDE shapes A–D (market-making / execution-overlay / convergence-bet / vol-MR)?

  [ yes: name it — verdict reopens, screen that shape ]
  [ no: verdict stands — vol-dislocation closes on §4 bullet 5 ]
```

## 6. What this means for the search space if the verdict stands

If no shape outside A–D exists, then vol-dislocation closes, and the new-program search space reduces to **A3 alone, itself pending definition** (`a3_definition.md`). Recall A3's fork: A3a (perp carry) is already killed; A3b (dated-futures carry) is untested only if dated-futures data exists in-substrate, else out-of-envelope. So if vol-dislocation closes here and A3 resolves to A3a-or-no-data, the new-program search space under the current envelope is **exhausted** — which `direction_map.md` already established as a legitimate, earned outcome, not a failure. The next move in that case is not "find another strategy from the existing mechanism set"; it is to identify an economic mechanism not represented anywhere on the map, or to accept exhaustion and shift the program's phase accordingly.

— end —

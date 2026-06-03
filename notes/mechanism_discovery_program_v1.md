# Mechanism Discovery Program v1

**Status:** Active filter, not a brainstorm. No signal, model, backtest, portfolio construction, or implementation work may begin on a mechanism family until it survives all four gates below. Verdicts here are **provisional pre-screen** — Gates 1 and 4 are largely chair-evaluable; Gate 2 (data) and Gate 3 (envelope) are operator-confirmed.
**Author:** Wasseem Katt
**Date:** 2026-06-03
**Purpose:** The direction map, combination screen, and Risk Standard v1.0 together proved that the exhausted resource is not *ideas* — it is *mechanisms already explored*. The funding, basis, momentum, and factor families are closed; rescue-by-combination is closed (no clean constituents). This program identifies economic mechanism families **not already on the map** and filters them before any signal research is opened. It answers the question the project has reduced itself to: *what economic mechanisms have never entered the map?*

> **Governing rule.** Passing Gate 1 (economic reality) is **necessary but not sufficient.** The project record already contains multiple mechanisms with plausible economic stories that failed on data (Sleeve B #2), robustness (Sleeve B #4), deployability (A1 burst-capture), sample (Section A), or envelope (A3). The discovery program exists to prevent economic plausibility from being mistaken for investability. A clean Gate 1 answer earns scrutiny on Gates 2–4, not a signal program.

## The four gates

**Gate 1 — Economic Reality.** Why should excess return exist? Must answer all three: who is paying, why are they paying, why doesn't competition eliminate it. A mechanism that cannot answer all three is rejected. (This is the gate that separates a *mechanism* from a *statistical pattern* — momentum and factor investing could never answer "who pays and why," which is why they degrade.)

**Gate 2 — Data Accessibility.** Can the required data be obtained inside the current envelope? Needs: data source identified, historical availability known, cost known, point-in-time feasibility known. Institutional-only or unavailable data → reject. (This is the gate Sleeve B #2 failed: PIT fee data structurally unavailable.)

**Gate 3 — Envelope Compatibility.** Can it be executed under the current envelope — solo operator, family capital, Risk Standard v1.0, existing venue infrastructure? Requires institutional infrastructure, heavy onboarding, latency arms-race, or major capital expansion → reject or classify Out-of-Envelope. (This is the gate A2, A3, and liquidity-provision failed.)

**Gate 4 — Map Novelty.** Is the mechanism genuinely absent from the direction map? Anything reducing to funding / basis / momentum / factor investing / vol-persistence / an existing closed family → reject. (Re-describing a killed family attractively does not make it new.)

## Excluded by reference (not re-screened here)

- **Liquidity Recovery** and **Spread Compression** — already screened under Vol-Dislocation (`vol_dislocation_same_object_test.md`, `vol_dislocation_liquidity_recovery_s4_screen.md`). Survived §6 novelty, provisional FAIL on §4 deployment shape. **Not eligible as new mechanism families** — they are a closed branch, not undiscovered ground. Listed here only to prevent their reappearance as "new" ideas.

## Candidate mechanism families — provisional pre-screen

| Family | Gate 1 (economic) | Gate 2 (data) | Gate 3 (envelope) | Gate 4 (novelty) | Provisional verdict |
|---|---|---|---|---|---|
| **Token Unlock Mechanics** | **PASS** — payer: holders forced to absorb scheduled supply; reason: calendar-known unlock, but realized vs priced-in impact is contested; persistence: naive version arbitraged, but the second-order question (does realized impact systematically differ from anticipated) is testable | Provisional PASS — unlock schedules public (vesting contracts on-chain, unlock trackers); PIT feasibility to confirm | Provisional PASS — calendar-driven, low-frequency, weekly-cadence tradeable; no latency/onboarding/scale requirement obvious | PASS — absent from map | **MOST LIKELY CURRENT SURVIVOR** — the only candidate with no obvious gate failure. Not "recommended"; "no disqualifier found yet." |
| **Liquidation Dynamics** | **PASS** (strong) — payer: forced sellers/buyers transacting price-insensitively; reason: liquidation engine protects venue, not fill; persistence: partially arbitraged but timing unpredictable and absorption is real risk-capital | Unknown — needs liquidation feed / cascade reconstruction; availability and PIT to confirm | **Provisional FAIL** — capturing it means providing liquidity into a cascade in the seconds-to-minutes window, capital at risk at peak stress; same execution wall that killed A2 and liquidity-provision; bumps §4 frequency boundary | PASS — absent from map | Strongest economics on the page, likely dies on Gate 3 envelope — same place A2 died. |
| **Staking / Validator Economics** | PASS — payer: non-stakers via issuance dilution; reason: protocol pays for security; persistence: yield is structural | PASS (provisional) — staking yields and flows largely public | **Provisional FAIL** — likely requires running infrastructure (nodes/validators) or capital lockup with unbond periods that collide with trading liquidity; may need a different capital structure than this program | PASS — absent from map | Not obviously impossible in-envelope, but probably needs a capital/operational structure outside the current one. |
| **Governance Mechanics** | Partial — payer/persistence unclear; governance "arbitrage" often requires moving votes (capital scale) | Unknown | **Provisional FAIL** — requires capital scale to influence governance or deep protocol-specific operational involvement | PASS — absent from map | Out-of-envelope until proven otherwise. |
| **MEV / Execution Structure** | PASS — payer: transactors whose ordering is exploited; reason/persistence: real and structural | N/A at this envelope | **FAIL** — latency/infrastructure arms race; the institutional-execution wall §4 bullet 4 explicitly excludes | PASS — absent from map | Out-of-envelope. Strong mechanism, wrong envelope — a well-capitalized low-latency operator's game, not a solo family-capital one. |
| **Other** | — | — | — | — | Reserved for a mechanism not above. Must answer all four gates from scratch. |

## Reading the pre-screen

Seven candidate names (including the two excluded-by-reference) filter to a clear ranking, and the filtering *is* the result:

- **2 deleted as already-mapped:** Liquidity Recovery, Spread Compression (the vol-dislocation branch).
- **4 provisional Gate-3 / envelope deaths:** Liquidation Dynamics, Staking, Governance, MEV — several with genuinely strong Gate 1 economics, all colliding with what a solo family-capital operator can execute. (Note the pattern: the strongest *economic* mechanisms on the page are the ones the *envelope* can't reach. That is itself a finding — it suggests the binding constraint on this program is not "are there real mechanisms" but "are there real mechanisms a solo operator at family-capital scale can execute.")
- **1 genuine live candidate:** **Token Unlock Mechanics** — the only family with no obvious disqualifier across all four gates.

If deeper scrutiny confirms Token Unlocks is the sole survivor, that is valuable: the discovery program reduced seven attractive ideas to one candidate worth a real pre-screen, *before a single signal was generated* — exactly the efficiency the project has been building toward. If it too fails on closer Gate 2/3 inspection, the map's exhaustion conclusion becomes much stronger, and the fork collapses toward "accept completion or expand the envelope."

## Next step (one, cheap)

A focused pre-screen of **Token Unlock Mechanics** against all four gates at full depth — confirming Gate 2 (is unlock-schedule + price data PIT-accessible in-substrate?) and Gate 3 (is the realized-vs-anticipated-impact trade executable on weekly cadence at family-capital scale under Risk Standard v1.0?). Paper only. No signal, no backtest, until it clears.

If Token Unlocks clears that deeper pre-screen, **then** — and only then — a signal research program opens, pointed at that one mechanism family, with candidates tested against Risk Standard v1.0. Not before.

## Recording rule

Mechanism families that fail are recorded on the direction map (status: out-of-envelope, or closed) before any signal generation begins — so the discovery program, like every prior screen, closes directions on the record rather than leaving them as open "maybe"s for future-you to re-propose.

— end —

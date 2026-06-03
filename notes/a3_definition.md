# A3 — Definition (template, pending operator decision)

**Status:** Open template. A3 has no source specification in the repo — it exists only as a label in the roadmap and in discussion. This note does not define A3; it states the fork that must be resolved before A3 can be screened, and ends on a required operator decision. **Nothing below is a spec.**
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Why this is a template, not a verdict:** there is no `a3_*` design document in the project record. The only "A3" string in the kill record (`sleeve_b_quality_kill_action.md`) refers to an unrelated data-source reformulation, not a cash-and-carry strategy. So A3's content is a decision the operator holds, not a fact recoverable from records. Drafting the answer would be inventing the spec — forbidden by the project's define-before-build discipline.

---

## 1. The fork: two completely different things hide under "A3"

### A3a — perp-funding / spot-perp carry

Construction: long spot, short perp, harvest funding. If this is what A3 means, it is **not untested.** It sits directly on top of directions already terminal on the map:

- **A1** (fixed-threshold and burst-activation funding capture) — data-limited and operationally rejected.
- **Naive funding carry** — empirically killed (§3.1), Sharpe ~10.7 diagnosed as a cashflow artifact.
- **Same-venue basis carry** (Binance perp/spot) — empirically killed (§3.1), net edge absent at size.

If A3 = A3a, it is **already killed** and does not earn a §4 screen. It would move straight to the empirically-killed column with a pointer to the A1 / naive-funding / same-venue-basis rows.

### A3b — dated-futures cash-and-carry

Construction: spot (e.g. BTC) vs **dated quarterly futures**, capturing the locked basis to expiry. If this is what A3 means, it is **genuinely distinct**: different instrument (dated quarterly, not perp), different economic mechanism (calendar basis converging to zero at expiry, not perpetual funding), different financing and roll structure. Nothing on the map measures this object. A3b is the only branch that earns a §4 screen.

## 2. The data-substrate question (may close A3b before any screen)

A3b cannot be screened — let alone specified — unless the data to test it exists in-substrate. The entire project data substrate is **Binance perp + spot**: every fetcher (`BinanceArchiveTradeFetcher`, `BinanceSpotArchiveTradeFetcher`), every fixture, the funding series. Dated quarterly futures are a different instrument class. Before A3b is eligible for a §4 screen, the following must be answered:

1. **History coverage.** Is there dated-quarterly-futures archive history of sufficient length and quality for an OOS window comparable to other probes (multi-year)?
2. **Roll mechanics.** Are the contract roll dates, expiry mechanics, and continuous-series construction rules available and reconstructable from the archive?
3. **Tradable contract coverage.** Are the contracts that would be traded actually liquid and accessible under the program's account/venue setup at the relevant horizons?

If the answer to any of these is no, A3b is **out-of-envelope on data availability** — the same structural wall that killed Sleeve B #2 (point-in-time fee data structurally unavailable). In that case A3b moves toward out-of-envelope *without* a §4 screen, and since A3a is already-killed, **A3 closes entirely on definitional + data grounds.**

## 3. Consequence table

| If A3 is defined as… | Then A3 is… | Next gate |
|---|---|---|
| A3a (perp-funding / spot-perp carry) | Already empirically killed (A1 + naive funding + same-venue basis) | None — move to killed column |
| A3b (dated-futures cash-and-carry) AND data exists | Genuinely untested | §4 screen (capital efficiency at $50k is the likely binding constraint) |
| A3b but dated-futures data does NOT exist in-substrate | Out-of-envelope (data availability) | None — move to out-of-envelope; A3 closes |
| Something else | Undefined | State it; re-run this fork |

## 4. Eligibility statement

> **A3 is not eligible for a §4 screen until this fork is resolved.** As written, "A3 cash-and-carry" is a label without a measured object. A screen run against an undefined direction is wasted motion — and under one branch (A3a) the screen is unnecessary because the direction is already killed.

## 5. Operator decision required

```
A3 = [ perp carry (A3a)  /  dated-futures carry (A3b)  /  other ]
```

And, if A3b:

```
Dated quarterly futures data in-substrate?  [ yes / no / unknown — needs a data-availability check ]
```

Once both are answered, A3's row on `direction_map.md` resolves to one of: empirically-killed (A3a), untested-and-§4-eligible (A3b + data), or out-of-envelope (A3b, no data). Until then it stays Untested / pending-definition and earns nothing.

— end —

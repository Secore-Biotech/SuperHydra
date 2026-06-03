# A3 — Definition and Status (resolved from records)

**Status:** Resolved. A3 is **defined** by the roadmap (not undefined as previously assumed) and is **structurally deferred** by program design. This note replaces the earlier template. No probe, no code, no spec.
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Supersedes:** the prior `a3_definition.md` template, which assumed A3 had no source definition. It does — `SuperHydra_FreshStart_Roadmap_v2_1.docx §3.1.3` defines it. The operator-decision the template requested is unnecessary; the roadmap already made it.

---

## 0. Disambiguation (two unrelated "A3" labels in the repo)

Grep for "A3" returns two things that share a string and nothing else:

- **Sleeve B Stage-A sub-gate A3** — "source agreement," a data-integrity check in the Sleeve B pre-registration framework (e.g. candidate #2's DeFiLlama-vs-on-chain reformulation). **Irrelevant here.**
- **Sleeve A engine A3** — the cash-and-carry engine. **This note.**

Anyone re-greping later must not conflate them.

## 1. What A3 is (from the roadmap, verbatim source)

`§3.1.3 Engine A3 — Cash-and-carry`:

> "Deferred until later. Adds futures-venue onboarding (Deribit or CME), which is operational friction not warranted on day one. Promoted only when A1 and A2 are both at scale and the engineering team has bandwidth for a venue addition without disrupting either."

And `§3.1` lists A3 as "cash-and-carry on **BTC futures vs spot**." So the fork is settled by the source:

- **A3 = A3b (dated-futures cash-and-carry): long/short BTC spot against a dated futures contract (Deribit or CME), capturing calendar basis as it converges to zero at expiry.**
- A3 is **not** A3a (perp-funding carry). Perp carry is A1's domain; the roadmap treats A1/A2/A3 as three independent engines (`§3.1`, `§A.2`). The A3a branch of the earlier template is void — it was never what A3 meant.

## 2. Why A3 is distinct from every killed direction

| Dimension | Killed funding/basis directions | A3 (dated-futures cash-and-carry) |
|---|---|---|
| Venue | Binance perp/spot | **Deribit or CME** (dated futures) |
| Instrument | Perpetual contracts | **Dated quarterly futures** |
| Mechanism | Perpetual funding / perp-spot basis | **Calendar basis converging to zero at expiry** |
| Return source | Funding payments / spot-perp spread | **Spot-vs-dated convergence (locked carry to expiry)** |

This is a genuinely different measured object from A1 (funding), A2 (perp-vs-spot basis), and the §3.1 same-venue/cross-venue basis kills. A3 is **not** already-killed.

## 3. Why A3 is not a live near-term candidate anyway — its promotion gate is unreachable

A3 being distinct does not make it pursuable now. The roadmap defers A3 explicitly, and the deferral is structural, not incidental:

1. **Data/infrastructure precondition.** A3 requires Deribit or CME dated-futures onboarding — data, contract/roll mechanics, and a tradable venue not in the current substrate (Binance perp/spot/funding/metrics). The roadmap calls this "operational friction not warranted on day one." This is a `§4` bullet-4 footprint cost (net-new venue integration) and a data-availability wall comparable to the one that killed Sleeve B #2 (PIT data structurally unavailable).
2. **The promotion precondition is now unreachable.** A3's stated gate is "promoted only when **A1 and A2 are both at scale**." As of the direction map (`c9d1c17`): **A1 is operationally rejected, A2 is empirically killed.** Neither will reach scale. So A3's own promotion condition can never be satisfied under the program as it stands.

A3 is therefore **defined, distinct, and structurally blocked** — not by lack of edge (untested), but because the infrastructure to test it is out-of-scope by design and the precondition that would justify that infrastructure (A1/A2 at scale) has failed.

## 4. Status assignment for the direction map

> **A3 (dated-futures cash-and-carry) — Out-of-envelope (infrastructure), conditional.**
> Defined as A3b. Genuinely distinct from all killed directions. Requires Deribit/CME dated-futures onboarding the substrate does not have and `§4` defers; its roadmap promotion gate ("A1 and A2 both at scale") is unreachable now that A1 is operationally rejected and A2 is killed. Economic status UNTESTED — this is a scope/infrastructure block, not an edge verdict. Re-eligible only if the program deliberately chooses to fund futures-venue onboarding as a standalone bet, independent of the (failed) A1/A2-at-scale precondition.

## 5. The one decision that remains (and it is NOT "what is A3")

A3's definition is settled. The only open question is a program-level one, and it is genuinely the operator's:

```
Does the program fund Deribit/CME dated-futures onboarding as a STANDALONE bet —
i.e. decouple A3 from its original "A1 and A2 at scale" precondition —
given that A3 is now the only distinct, non-killed trading object left
but sits entirely behind net-new venue infrastructure?

  [ no:  A3 stays out-of-envelope; the new-program trading search space is exhausted ]
  [ yes: A3 becomes a deliberate infrastructure investment; write its §4 screen
         against the standalone-onboarding cost, NOT against the dead A1/A2 gate ]
```

This is not a "define A3" decision (done) and not a "find a strategy" decision. It is a capital/scope decision about whether to build a new venue integration to test the last distinct object on the map. Under the family-capital mission and the $50k / solo-operator envelope, the prior leans **no** — venue onboarding for a single deferred engine is heavy infrastructure for an untested edge — but that is the operator's call, not a records fact.

— end —

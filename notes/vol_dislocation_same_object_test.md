# Volatility Dislocation — §6 Same-Object Screen

**Status:** Final — screen, not a spec. Decides whether any vol-dislocation formulation is a genuinely new measured object or Section A re-described. No probe, no code, no pre-registration.
**Author:** Wasseem Katt
**Date:** 2026-06-02
**Gate applied:** `edge_scoping.md §6` — a direction is open only if the *measured object* differs from directions already killed; "the same statistical object in a longer observation window is not a new direction." Also checked against `§3.1` (basis/funding kills) and the A1/A2 records, because a formulation can clear §6 (not Section A) yet still be dead for a *different* reason (already-killed cluster).
**Inputs:** `2026-05-28-vol-event-persistence-probe-outcome.md` (Section A's measured object), `edge_scoping.md §3.1`/`§6`, `a1_*`/`a2_kill_action.md` (collision clusters), `direction_map.md` (`c9d1c17`).

---

## 1. What Section A already measured (the object to be distinct from)

Section A's measured object, from its outcome record: **a volatility shock event (24h realized σ crossing the trailing-90-day P95 threshold) → subsequent directional price behavior over 1/3/7-day horizons.** The object is *price-return persistence conditioned on a vol event*. Section A is data-limited, not killed — but for §6 purposes what matters is the *object*, not the verdict. Any new formulation whose measured object reduces to "vol event → future price return" is the same object at a different horizon and is rejected by §6 regardless of how it is dressed.

## 2. The §6 test applied to each candidate object

For each candidate: state the measured object, compare to Section A, then check whether it collides with a *different* already-killed cluster.

### 2.1 vol shock → future returns — **REJECT (§6, same object)**

This is Section A. Measured object = directional price return conditioned on a vol event. Whether the horizon is 1 day, 7 days, or 30 days, it is the same statistical object Section A already tests. §6 kills it explicitly: a timeframe change on the same object is not a new direction. Not eligible.

### 2.2 vol shock → funding behavior — **CLEARS §6, but COLLIDES with the A1/funding cluster**

The measured object (does funding respond to a vol shock?) is *not* Section A's object — it is not a price-return object. So it passes the §6 same-object test. But it routes directly into the funding work already on the map: A1 (fixed-threshold and burst-capture, both terminal), naive funding carry (§3.1 empirically killed). If "funding behavior" means "funding spikes after vol," the spike regime is the *same burst regime* the A1 burst-activation screen already characterized — episodic, ~3–7% duty cycle, dormant since 2024-12. Measuring "vol predicts funding bursts" does not escape that: it would, at best, be a *predictor* of the same dormant burst regime that was already operationally rejected. **Clearing §6 is necessary, not sufficient. This object is dead on the A1 cluster unless it can state a funding phenomenon distinct from the burst regime already mapped — and the burden is on the formulation to show that.**

### 2.3 vol shock → basis behavior — **CLEARS §6, but COLLIDES with the A2/basis cluster**

Same structure as 2.2. The object (does basis respond to a vol shock?) is not Section A's price-return object, so it passes §6. But it collides with the basis kills: same-venue basis carry (§3.1, killed), cross-venue basis (§3.1, killed), and especially **A2 perp-vs-spot basis** — whose kill finding is precisely that basis dislocations are *stress-event harvesters*: they fire only during liquidation cascades where execution is unmeasured and unviable (the Sep-2021 SOL 70-minute cascade, 7 of 8 trades in one window). "Vol shock → basis behavior" is, on the A2 evidence, measuring the *same stress-conditioned basis dislocation* A2 already characterized and shelved on execution grounds. **Clears §6, dead on the A2 cluster unless it states a basis phenomenon distinct from stress-cascade harvesting.**

### 2.4 vol shock → liquidity recovery / spread compression — **SURVIVES**

Measured object = the **reconstitution of market microstructure after a shock**: how order-book depth recovers, how bid-ask spread compresses back toward baseline, over what timescale, following a vol event. This is:

- **Not Section A** — it is not a price-return object. Direction of price is irrelevant; the object is depth/spread *recovery dynamics*. Passes §6.
- **Not the funding cluster** — funding rate is not the measured variable.
- **Not the basis cluster** — basis is not the measured variable, and the object is not a stress-cascade entry signal; it is a recovery-trajectory measurement.
- **Not on the map at all** — no prior direction measures microstructure recovery. It is genuinely untested.

This is the one vol-dislocation object that survives §6 *and* avoids every already-killed cluster. It is therefore the only formulation eligible to proceed — and even so, only to a §4 screen, not a spec.

## 3. Verdict

| Candidate object | §6 (vs Section A) | Collision cluster | Status |
|---|---|---|---|
| vol shock → future returns | REJECT (same object) | — | Dead (§6) |
| vol shock → funding behavior | clears §6 | A1 / funding | Dead on A1 cluster unless distinguished |
| vol shock → basis behavior | clears §6 | A2 / basis | Dead on A2 cluster unless distinguished |
| vol shock → liquidity recovery / spread compression | clears §6 | none | **Survives — eligible for §4 screen** |

**One survivor: liquidity-recovery / spread-compression after a vol shock.** It is a genuinely distinct measured object, untouched by Section A and by every killed cluster.

## 4. What this does NOT establish

- It does **not** make liquidity-recovery a spec. It is one survivor of a same-object screen, nothing more. The next gate is `§4` (is a microstructure-recovery strategy operationalisable under the $50k / solo-operator / runway envelope?) — and there is an obvious risk it fails there, because microstructure-recovery edges often require low-latency execution and depth that retail-scale capital cannot reach. That is a `§4` question, not a `§6` one, and is not pre-judged here.
- It does **not** establish that liquidity-recovery has any edge. §6 is a *novelty* gate, not an economic one. Surviving §6 means "worth screening," not "worth building."
- The two collision cases (funding, basis) are **not** reopened. They clear §6 only in the trivial sense that they are not Section A; they remain dead on their own clusters. Listing them here is to document why they are not the survivor, so they are not re-proposed later as "new vol-dislocation ideas."

## 5. Next action (if pursued)

The §4 screen for liquidity-recovery / spread-compression — paper-only, no code — answering: can a strategy whose edge is post-shock microstructure reconstitution be executed under the program envelope, or does it require depth/latency outside `§4` bullets 3–5? Run that before any spec. If it fails §4, this object moves to out-of-envelope and the vol-dislocation direction is closed.

— end —

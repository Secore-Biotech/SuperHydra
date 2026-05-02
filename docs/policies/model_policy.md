# Model Policy

**Version:** 1.1
**Effective:** 2026-05-02 (revised from v1.0 same date)
**Author:** Wasseem Katt
**Source:** Lopez de Prado validation methodology; HYDRA postmortem 2026-05-01; SuperHydra Enhanced Plan; v1.1 incorporates external review 2026-05-02
**Supersedes:** v1.0 (same date)

This policy defines what counts as a validated model in SuperHydra. Models are research artifacts that produce alpha signals or risk decisions; their lifecycle is governed here, while the gates they must clear are defined in deployment_gates.md and the PnL they produce is typed per measurement_policy.md.

## Why v1.1

v1.0 was implicitly ML-centric -- every model was assumed to be a predictive alpha model evaluated by OOS Sharpe, DSR, PSR. This would reject perfectly valid non-ML strategies that don't fit the predictive-Sharpe frame: a covered-call options overlay (negative standalone Sharpe but reduces drawdown), a basis trade (judged by carry net of unwind cost), a microstructure execution filter (judged by slippage reduction). v1.1 adds a strategy-class taxonomy with class-specific validation criteria.

## 1. Pre-research check (game expected-value gate)

Unchanged from v1.0. Before any model is trained, the underlying game's expected value at intended deployment size must be computed and shown positive after spread, fees, and slippage.

**Computation requirement:**
- Bid-ask spread at intended order size (not top-of-book): measured from L2 order book data
- Maker and taker fees per the venue's fee schedule at intended volume tier
- Funding rate impact for perpetual positions over expected hold duration
- Slippage estimate from cost model at intended size against typical order book depth

**Admission thresholds:**
- EV >= 0.5% per round-trip net of all costs: research-phase admission granted automatically
- 0% <= EV < 0.5% (marginal): explicit operator override required with documented rationale in `docs/decisions/`
- EV < 0%: auto-rejected, no override permitted

The PM Bot 5-minute crypto binary strategy is the canonical anti-example.

## 2. Strategy class taxonomy (v1.1 addition)

Every strategy is classified into one of six classes at admission. The class determines which validation criteria apply.

### Class A -- Predictive alpha model

**Examples:** market-neutral L/S, directional momentum, mean-reversion.
**Judged primarily by:** OOS Sharpe, DSR, PSR, IC (information coefficient).
**Phase 1 admitted classes:** LightGBM, XGBoost, CatBoost, ElasticNet, Lasso, Ridge, Random Forest.
**Phase 1 forbidden classes:** Deep learning models (LSTM, Transformer, CNN-LSTM) -- forbidden until tree models have been beaten on cost-modeled OOS Sharpe across at least 3 walk-forward periods. Black-box ensembles where individual feature contribution is not auditable.

**Validation requirements (full pipeline):**
- Walk-forward Sharpe >= 3.0 cost-modeled
- DSR > 0
- PSR >= 0.95 against null Sharpe of 1.0
- Combinatorial purged CV: median fold Sharpe >= 2.5, no fold < 1.0
- Lookahead bias test passed
- Survivorship bias test: Sharpe degradation <= 30% on full universe replay
- Multiple-testing correction (Bonferroni or BH) on factor selection
- Cost-stress sensitivity: Sharpe >= 1.5 in worst case (+/-50% cost perturbation)
- Capacity estimate >= $100,000

### Class B -- Carry / basis / funding strategy

**Examples:** long spot / short perp when funding strongly positive, cross-exchange funding dispersion, calendar spread convergence.
**Judged primarily by:** net carry edge after unwind cost, hedge quality, basis convergence behavior, venue risk.
**Not judged by:** OOS Sharpe alone (carry strategies have different statistical signature than predictive alpha; high hit rate, small per-trade PnL, occasional large unwind losses).

**Validation requirements:**
- Net carry edge >= 2x expected unwind cost (entry rule)
- Hedge ratio stability: spot leg and perp leg track each other within 1% over expected hold duration in historical replay
- Stress test: funding reversal scenario shows <= 50% drawdown of carry earned
- Stress test: venue outage on one leg can be unwound through alternative path within 4 hours
- Realized cost (fees, slippage, borrow) modeled and verified against historical carry trades
- Capacity estimate >= $100,000 (carry alpha typically scales worse than directional alpha)
- DSR > 0 on the realized carry distribution (not on Sharpe of equity curve, which is misleading for carry)

### Class C -- Options / volatility hedge or alpha

**Examples:** protective put overlay, IV/RV spread, delta-hedged volatility strategy, tail hedge.
**Judged primarily by:** drawdown reduction (for hedges) OR realized vol-spread capture net of theta decay (for alpha). Negative standalone Sharpe is acceptable for hedge strategies if portfolio drawdown reduction justifies cost.
**Forbidden until canary-proven:** naked short options, unhedged short gamma, large vega exposure.

**Validation requirements (hedge variants):**
- Portfolio expected shortfall reduction at 95% confidence >= hedge cost over 12-month historical replay
- Maximum drawdown reduction in stress scenarios (BTC -30%, vol spike) >= hedge cost
- Greeks tracking: delta/gamma/vega exposure stays within risk_policy section 11 limits
- Hedge cost stable: monthly premium spent within budget over 12-month replay

**Validation requirements (alpha variants):**
- Cost-modeled OOS Sharpe >= 2.0 (lower bar than Class A because options strategies generally have lower Sharpe with higher tail risk)
- DSR > 0 on realized PnL distribution
- Tail risk explicitly modeled (not just mean Sharpe -- left-tail size matters)
- Capacity estimate >= $50,000 (options markets shallower)

### Class D -- Execution model

**Examples:** microstructure filter (delays/cancels orders against adverse flow), maker-taker decision logic, smart routing.
**Judged primarily by:** slippage reduction vs baseline execution, adverse selection metrics post-fill, implementation shortfall improvement.
**Not judged by:** standalone Sharpe (execution layers don't have one -- they improve other strategies' fills).

**Validation requirements:**
- Realized slippage reduction >= 20% vs naive baseline (market-order or simple limit) on identical signal stream
- Adverse-selection score (post-fill price drift in unfavorable direction) reduced >= 30% vs baseline
- Maker fill rate >= baseline maker rate (if maker-taker decision logic)
- Implementation shortfall (entry vs decision price) <= baseline shortfall
- Tested across at least 3 market regimes (calm, vol spike, trending)

### Class E -- Risk overlay

**Examples:** regime detection (RISK_ON/FRAGILE/CRISIS state controller), drawdown-based exposure scaling, on-chain liquidity flag.
**Judged primarily by:** avoided drawdowns (true positives), false positive/negative rate on regime detection, portfolio-level Sharpe improvement when overlay is active vs disabled.
**Not judged by:** standalone Sharpe (overlays don't trade alone).

**Validation requirements:**
- Backtest with overlay vs without overlay across 12+ months including stress events: overlay version has <= 50% of unhedged drawdown in tested stress events
- False positive rate (overlay triggered RISK_OFF but no actual stress event followed within 7 days): <= 30%
- Detection lag: overlay reaches RISK_OFF within 24 hours of stress event onset in historical replay
- Portfolio Sharpe with overlay enabled >= portfolio Sharpe without overlay over the full 12-month window
- Regime transitions are explainable: every state transition logs which inputs caused it

### Class F -- Sentiment / news / event classifier

**Examples:** NLP-based event taxonomy, source credibility scoring, sentiment-aware position sizing.
**Judged primarily by:** classification accuracy (precision/recall on event types), signal half-life, portfolio improvement when classifier output is consumed by allocator or risk overlay.
**Forbidden:** direct order placement based on sentiment alone (must route through Class A predictive model or Class E overlay that consumes the signal).

**Validation requirements:**
- Event classification F1 score >= 0.7 on labeled test set
- Source credibility calibration: high-credibility sources verified to produce true-positive event rate >= 80%
- Signal half-life measured per event type (how long after event onset does the signal retain predictive value)
- Bot/manipulation filter: known-manipulated content is rejected at >= 90% rate on test set
- Portfolio Sharpe with classifier consumed >= Sharpe without classifier over 12-month replay
- Output object contains all required fields per data_policy section on sentiment data structure

## 3. Validation pipeline (applies primarily to Class A; other classes use class-specific pipeline)

For Class A strategies, the validation pipeline uses Lopez de Prado's mlfinlab library or equivalent.

**Required validations for Class A:**

| Validation | Tool | Pass threshold |
|---|---|---|
| Walk-forward Sharpe | Custom over rolling windows | >= 3.0 cost-modeled |
| Deflated Sharpe Ratio (DSR) | mlfinlab | DSR > 0 |
| Probabilistic Sharpe Ratio (PSR) | mlfinlab | PSR >= 0.95 against null Sharpe of 1.0 |
| Combinatorial Purged Cross-Validation | mlfinlab | Median fold Sharpe >= 2.5; no fold < 1.0 |
| Lookahead bias test | Custom: shuffle future returns, retest | Sharpe collapses to <= 0.5 |
| Survivorship bias test | Universe replay including delisted assets | Sharpe degradation <= 30% |
| Multiple-testing correction | Bonferroni or BH on factor selection | Surviving factors only used |
| Cost-stress sensitivity | Cost model perturbation +/-50% | Sharpe >= 1.5 in worst case |

**Walk-forward window requirements:**
- Minimum 12 months of historical data
- Train window minimum 6 months, rolling
- Test window minimum 1 month, never seen during training
- Embargo period 2 weeks between train and test windows
- Minimum 6 walk-forward folds

**Classes B-F:** validation pipeline is class-specific per section 2 above. DSR/PSR computed where they make sense (Class B carry distribution, Class C alpha variants). Where Sharpe is not the primary metric, the class-specific metric replaces it.

## 4. Feature governance (unchanged from v1.0)

**Every feature used in a model must be:**
- Registered in the feature store with a unique ID
- Versioned (changes to feature computation create new feature ID, not in-place modification)
- Tested for parity between research and live computation paths (parity test passes nightly)
- Documented with: definition, computation, data sources, refresh cadence, expected range
- Cleared through lookahead-bias review

**Forbidden in features:**
- Future information at time t (lookahead bias)
- Data from sources not in `data_policy.md` vendor list
- Computations that differ between research and live paths
- Magic constants without committed rationale

**Feature universe sizing:**
- Phase 1 starts with 30-50 features. Not 5,000.
- New features are added one at a time, each with documented hypothesis and validation
- Features that fail validation are removed, not retained "for diversity"

## 5. Training data hygiene (unchanged from v1.0)

**Data must be:**
- Pulled from sources tagged `VERIFIED` per measurement_policy.md
- Free of look-ahead leakage (verified by lookahead bias test)
- Time-stamped in UTC with venue clock alignment verified
- Survivorship-bias controlled
- Reproducible

**Splits:**
- Train / validation / test splits are time-ordered, never shuffled
- Test set is held out and not consulted during model selection
- Validation set may be consulted for hyperparameter selection but never for final selection criteria

**Retraining cadence:**
- Models retrain on a fixed schedule, not in response to performance
- Default cadence for Class A: weekly retrain on 6-month rolling train window
- Default cadence for Class B/E: monthly retrain
- Class C/F: per-engine specification
- Performance-triggered retrains are forbidden (creates selection bias)

## 6. Model selection and ensembling

**Selection from candidate set:**
- Multiple candidate models trained per problem
- Selection criterion is OOS validation performance per class-specific metric, not in-sample fit
- Selection is automated based on pre-registered criteria
- Tie-breaking favors simpler models

**Ensembling:**
- Phase 1 starts with single best model per problem for Class A
- Class A ensembles admitted only when multiple individually-validated models exist and combination is independently validated
- Ensemble weights are fixed at training time, not dynamic
- Total ensemble size capped at 5 models in Phase 1; 20 in Phase 6

**Cross-class ensembling (v1.1 clarification):**
A portfolio combining Class A predictive alpha + Class B carry + Class E regime overlay is not an "ensemble" per the cap -- it's a multi-sleeve allocation governed by allocator_policy.md. The 5-model cap applies within a single class.

## 7. Drift monitoring (unchanged from v1.0)

Every production model is monitored continuously for drift:

| Metric | Computation | Action threshold |
|---|---|---|
| Prediction drift | KL divergence between recent and reference predictions | Flag at 0.1, halt at 0.3 |
| Feature drift | KS test on feature distributions vs training | Flag at p < 0.01, halt at p < 0.001 |
| Performance drift | Realized class-metric vs validation class-metric | Flag at 50% gap, halt at 75% gap |
| Cost model drift | Realized cost vs modeled cost | Flag at 30% gap, halt at 50% gap |

Halt suppresses model output; existing positions are managed by hold-or-close logic only. Re-enabling requires retrain or model reselection.

## 8. Model versioning (unchanged from v1.0)

Every model deployed to any environment has a version ID:
- Format: `<strategy>_<class>_<model_class>_<training_data_version>_<feature_version>_<hyperparam_hash>_<train_date>`
- Example: `mn_ls_classA_lgbm_data_v3_features_v2_a3f9c1_20260615`
- Version registered in `model_registry` table
- Model artifact committed to S3/MinIO with version ID as key
- Live model in production is referenced by version ID, not file path

**Forbidden:**
- Overwriting a model file in place
- Deploying a model whose version is not in the registry
- Loading a model from a path that does not match the registry version

Every prediction made by a production model is logged with the model version ID.

## 9. Backtest hygiene (unchanged from v1.0)

**Required for any backtest result reported:**
- Cost model applied (modeled fills, fees, funding, slippage)
- Survivorship bias controlled
- Lookahead bias verified absent
- Walk-forward, not single in-sample / out-of-sample split
- Class-appropriate metrics computed and reported (DSR/PSR for Class A; carry-net-of-unwind for Class B; etc.)
- Capacity estimate at intended deployment size
- Drawdown distribution, not just maximum

**Forbidden:**
- Reporting in-sample Sharpe as a primary metric
- Reporting Sharpe without DSR/PSR (for Class A)
- Reporting backtests with leverage applied retrospectively to historical no-leverage runs
- Visual selection of "best" walk-forward window
- Backtests that include data later than the model's training cutoff

## 10. Operator override (unchanged from v1.0)

In rare cases an operator may need to override a model decision. Override requires:
- Recorded operator override event with rationale
- Time-bounded (default 1 trading session, max 1 week)
- Override resolves to either re-enable model authority or sunset the model
- Frequent overrides indicate the model is not trusted

**Forbidden:**
- Routine human overrides "to make the equity curve look better"
- Overrides that bypass risk_policy limits
- Overrides without rationale

## 11. Quarterly model review

A model review runs quarterly. It:
- Audits all production models for drift status
- Reviews any model that triggered halt or override during the quarter
- Re-validates the validation pipeline itself
- Reviews feature universe for stale or redundant features
- Validates strategy-class assignments are still correct
- Updates this policy if calibration is needed

**Sign-off:** Operator (Wasseem Katt). Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## 12. Policy hierarchy

This policy is part of the SuperHydra Policy Pack. When policies conflict:

1. Safety/compliance/venue permission requirements
2. Risk policy
3. Measurement policy
4. Deployment gates policy
5. Data policy
6. Model policy (this document)
7. Allocator policy
8. Incident severity policy

The stricter safety/risk interpretation applies until policies are amended and re-signed.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy with tree-model class, mlfinlab validation, 30-50 feature ceiling for Phase 1 |
| 1.1 | 2026-05-02 | Wasseem Katt + external reviewer | Added strategy-class taxonomy (Classes A-F: predictive alpha, carry/basis, options, execution, risk overlay, sentiment classifier) with class-specific validation requirements. Clarified cross-class ensembling vs within-class ensembling. Added class-specific retraining cadence defaults. Added strategy-class assignment validation to quarterly review. Added policy hierarchy. |

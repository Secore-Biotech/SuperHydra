# Model Policy

**Version:** 1.0
**Effective:** 2026-05-02
**Author:** Wasseem Katt
**Source:** Lopez de Prado validation methodology; HYDRA postmortem 2026-05-01; SuperHydra Enhanced Plan

This policy defines what counts as a validated model in SuperHydra. Models are research artifacts that produce alpha signals; their lifecycle is governed here, while the gates they must clear are defined in deployment_gates.md and the PnL they produce is typed per measurement_policy.md.

## 1. Pre-research check (game expected-value gate)

Before any model is trained, the underlying game's expected value at intended deployment size must be computed and shown positive after spread, fees, and slippage. This is the lesson from PM Bot's 96% loss share on 5-minute crypto binaries.

**Computation requirement:**
- Bid-ask spread at intended order size (not top-of-book): measured from L2 order book data
- Maker and taker fees per the venue's fee schedule at intended volume tier
- Funding rate impact for perpetual positions over expected hold duration
- Slippage estimate from cost model at intended size against typical order book depth

**Admission thresholds (from measurement_policy.md section 9):**
- EV >= 0.5% per round-trip net of all costs: research-phase admission granted automatically
- 0% <= EV < 0.5% (marginal): explicit operator override required with documented rationale in `docs/decisions/`
- EV < 0%: auto-rejected, no override permitted

The EV computation is committed to `research/hypotheses/<strategy_name>.md` before any model code is written. Models written for negative-EV games are rejected at code review.

## 2. Validation pipeline

Every model that aims to advance to Shadow must pass the validation pipeline. The pipeline uses Lopez de Prado's mlfinlab library or equivalent.

**Required validations:**

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
- Embargo period 2 weeks between train and test windows (prevents leakage from autocorrelation)
- Minimum 6 walk-forward folds (typically more)

A model failing any required validation is rejected from Shadow admission. The failure does not auto-sunset the strategy -- return to Research for revision.

## 3. Model class restrictions

**Phase 1 admitted classes:**
- Tree-based ensembles: LightGBM, XGBoost, CatBoost
- Linear models with regularization: ElasticNet, Lasso, Ridge
- Random Forest

**Phase 1 forbidden classes:**
- Deep learning models (LSTM, Transformer, CNN-LSTM): forbidden until tree models have been beaten on cost-modeled OOS Sharpe across at least 3 walk-forward periods
- Black-box ensembles where individual feature contribution is not auditable
- Models trained on data not registered in the feature store
- Models with hyperparameters chosen by visual inspection of in-sample performance

The deep-learning restriction is deliberate. QAnalytics and most working crypto quant operations use tree models because they are interpretable, robust to outliers, and harder to overfit at the data scale available. Deep learning is admissible only after tree models have demonstrated insufficiency on the same problem.

## 4. Feature governance

**Every feature used in a model must be:**
- Registered in the feature store with a unique ID
- Versioned (changes to feature computation create new feature ID, not in-place modification)
- Tested for parity between research and live computation paths (parity test passes nightly)
- Documented with: definition, computation, data sources, refresh cadence, expected range
- Cleared through lookahead-bias review

**Forbidden in features:**
- Future information at time t (lookahead bias)
- Data from sources not in `data_policy.md` vendor list
- Computations that differ between research and live paths (causes drift between backtest and shadow)
- Magic constants without committed rationale

**Feature universe sizing:**
- Phase 1 starts with 30-50 features. Not 5,000.
- New features are added one at a time, each with documented hypothesis and validation
- Features that fail validation are removed, not retained "for diversity"

The 30-50 ceiling for Phase 1 is deliberate. QAnalytics' 5,000-factor universe assumes institutional compute and a team of researchers. SuperHydra Phase 1 is one founder; a smaller, well-curated feature set produces better OOS performance than a poorly-validated large set.

## 5. Training data hygiene

**Data must be:**
- Pulled from sources tagged `VERIFIED` per measurement_policy.md section 4
- Free of look-ahead leakage (verified by lookahead bias test)
- Time-stamped in UTC with venue clock alignment verified
- Survivorship-bias controlled: training universe includes delisted assets that existed at the historical time point
- Reproducible: the same script run on the same data produces identical training results

**Splits:**
- Train / validation / test splits are time-ordered, never shuffled
- Test set is held out and not consulted during model selection
- Validation set may be consulted for hyperparameter selection but never for final selection criteria

**Retraining cadence:**
- Models retrain on a fixed schedule, not in response to performance
- Default cadence: weekly retrain on 6-month rolling train window
- Performance-triggered retrains are forbidden (creates selection bias toward favorable conditions)
- Retrain frequency can be adjusted in this policy with revision; ad hoc retrains are not permitted

## 6. Model selection and ensembling

**Selection from candidate set:**
- Multiple candidate models trained per problem
- Selection criterion is OOS validation performance, not in-sample fit
- Selection is automated based on pre-registered criteria, not human judgment on equity curves
- Tie-breaking favors simpler models (fewer parameters, fewer features)

**Ensembling:**
- Phase 1 starts with single best model per problem, not ensembles
- Ensembling is admitted only when multiple individually-validated models exist and their combination has been independently validated
- Ensemble weights are fixed at training time, not dynamic
- Total ensemble size capped at 5 models in Phase 1; 20 in Phase 6

The ensemble cap is deliberate. QAnalytics runs 1,500 production models, but they have institutional infrastructure and a research team. SuperHydra Phase 1 starts simple and adds complexity only when justified by OOS evidence.

## 7. Drift monitoring

Every production model is monitored continuously for drift:

| Metric | Computation | Action threshold |
|---|---|---|
| Prediction drift | KL divergence between recent and reference predictions | Flag at 0.1, halt at 0.3 |
| Feature drift | KS test on feature distributions vs training | Flag at p < 0.01, halt at p < 0.001 |
| Performance drift | Realized Sharpe vs validation Sharpe | Flag at 50% gap, halt at 75% gap |
| Cost model drift | Realized cost vs modeled cost | Flag at 30% gap, halt at 50% gap |

Halt means: model output is suppressed, the strategy reverts to no-position state for new entries, existing positions are managed by hold-or-close logic only. Re-enabling requires either retrain (if drift is feature-based) or model reselection (if drift is performance-based).

## 8. Model versioning

Every model deployed to any environment (research, shadow, canary, scale) has a version ID:

- Version ID format: `<strategy>_<model_class>_<training_data_version>_<feature_version>_<hyperparam_hash>_<train_date>`
- Example: `mn_ls_lgbm_data_v3_features_v2_a3f9c1_20260615`
- Version registered in `model_registry` table
- Model artifact (serialized model file) committed to S3/MinIO with version ID as key
- Live model in production is referenced by version ID, not by file path

**Forbidden:**
- Overwriting a model file in place
- Deploying a model whose version is not in the registry
- Loading a model from a path that does not match the registry version

Every prediction made by a production model is logged with the model version ID, so historical predictions are reproducible.

## 9. Backtest hygiene

**Required for any backtest result reported:**
- Cost model applied (modeled fills, fees, funding, slippage)
- Survivorship bias controlled
- Lookahead bias verified absent
- Walk-forward, not single in-sample / out-of-sample split
- DSR computed and reported alongside Sharpe
- PSR computed and reported alongside Sharpe
- Capacity estimate at intended deployment size
- Drawdown distribution, not just maximum

**Forbidden:**
- Reporting in-sample Sharpe as a primary metric
- Reporting Sharpe without DSR/PSR
- Reporting backtests with leverage applied retrospectively to historical no-leverage runs
- Visual selection of "best" walk-forward window
- Backtests that include data later than the model's training cutoff

## 10. Operator override

In rare cases an operator may need to override a model decision (force-close a position the model wants to hold, force-flat the strategy in advance of a known event). Override requires:

- Recorded operator override event with rationale
- Time-bounded (default 1 trading session, max 1 week)
- Override resolves to either re-enable model authority or sunset the model
- Frequent overrides indicate the model is not trusted and should be evaluated for retirement

**Forbidden:**
- Routine human overrides "to make the equity curve look better"
- Overrides that bypass risk_policy limits
- Overrides without rationale

## 11. Quarterly model review

Alongside the measurement and risk reviews, a model review runs quarterly. It:
- Audits all production models for drift status
- Reviews any model that triggered halt or override during the quarter
- Re-validates the validation pipeline itself (verifies mlfinlab version, statistical thresholds, parity test results)
- Reviews feature universe for stale or redundant features
- Updates this policy if calibration is needed

**Sign-off:** Operator (Wasseem Katt). Both signatures required if/when a second operator joins.

**First quarterly review scheduled:** 2026-08-02

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-02 | Wasseem Katt | Initial policy with tree-model class, mlfinlab validation, 30-50 feature ceiling for Phase 1 |

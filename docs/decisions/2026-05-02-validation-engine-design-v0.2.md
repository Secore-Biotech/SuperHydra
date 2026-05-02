# Validation Engine Design v0.2

**Status:** Design draft, supersedes v0.1
**Author:** Wasseem Katt
**Date:** 2026-05-02
**Implements:** model_policy.md v1.1 strategy-class taxonomy and validation requirements; deployment_gates.md v1.1 Research -> Shadow gate; measurement_policy.md v1.1 environment/settlement typing; allocator_policy.md v1.0 portfolio contribution; data_policy.md v1.1 vendor-VERIFIED prerequisite
**Implementation target:** Phase 1 (May 11 - June 15 2026), specifically Phase 1 weeks 5-6 per the SuperHydra Enhanced Plan
**Supersedes:** v0.1 -- significant restructuring, not incremental edits

This document specifies the validation engine that gates strategies from Research to Shadow. v0.2 replaces v0.1 because v0.1's design produced false validation confidence in three ways: (1) hard-coded gate thresholds in code rather than reading from policy snapshots, (2) lookahead test as a single shuffle rather than a suite, (3) validation of `predictions -> returns` rather than `predictions -> optimizer -> orders -> fills -> ledger NAV`. v0.2 fixes all three.

## Why v0.2

v0.1 was reviewed and identified as "research-metrics engine more than complete strategy-validation engine." v0.2 upgrades to "full strategy replay through optimizer, cost model, and ledger simulator." Specific changes from v0.1:

1. mlfinlab is now accessed via a `ValidationBackend` protocol -- not a hard dependency. License risk and operational risk both mitigated.
2. CPCV uses explicit `LabelSpec` with prediction/label start/end times for proper purging.
3. Lookahead test is a six-test suite, not a single shuffle.
4. Gate thresholds live in `PolicySnapshot` objects loaded from policy doc versions, not in code.
5. Artifact integrity uses content hashes, not paths alone.
6. Reproducibility splits `scientific_config_hash` from `run_metadata_hash`.
7. Validation runs through optimizer and ledger simulator -- `predictions -> optimizer -> target_weights -> orders -> fills -> ledger entries -> NAV -> returns`.
8. Portfolio contribution metrics added (marginal Sharpe, correlation to existing sleeves, crisis correlation).
9. Conservative NAV / unrealized risk metrics added.
10. Classes B-F have interface support from day one with `NOT_IMPLEMENTED` ValidationStatus, not exception-raising stubs.
11. Validation schema separate from registry: `validation.reports`, `validation.fold_metrics`, `validation.bias_test_results`, `validation.artifacts`, `validation.policy_snapshots`.
12. `ValidationStatus` enum (PASS / FAIL / INCONCLUSIVE / NOT_IMPLEMENTED / NO_DATA / ERROR) -- distinguishes "could not run" from "ran and failed."
13. `GateDecision` separate from metrics report.
14. Class-specific configs implementing common Protocol.
15. Walk-forward retrains per fold from training pipeline artifact, not from one frozen model.
16. Cost stress documented as return-perturbation in v0.2 with explicit roadmap to fill re-simulation in v0.3.
17. Eight additional acceptance criteria from the v0.1 review.

## Why this engine exists

model_policy v1.1 defines six strategy classes with class-specific validation requirements. deployment_gates v1.1 requires every strategy to clear validation before Shadow admission. The validation engine is the runtime that:

1. Computes class-appropriate metrics
2. Replays the strategy through optimizer, cost model, and ledger simulator (not isolated `predictions -> returns`)
3. Tests for lookahead bias (suite), survivorship bias, multiple-testing correction
4. Computes portfolio contribution against currently-active strategies
5. Produces a validation report committed to the ledger
6. Returns pass/fail per gate criteria with full provenance, where thresholds come from policy snapshots not hard-coded code

## Module structure

```
hydra-next/research/validation/
|-- __init__.py
|-- engine.py                       # Top-level ValidationEngine
|-- status.py                       # ValidationStatus enum
|-- config/
|   |-- __init__.py
|   |-- scientific.py               # ScientificValidationConfig
|   |-- run_metadata.py             # ValidationRunMetadata
|   |-- class_a_config.py           # ClassAConfig (predictive alpha)
|   |-- class_b_config.py           # ClassBConfig (carry)
|   |-- class_c_config.py           # ClassCConfig (options)
|   |-- class_d_config.py           # ClassDConfig (execution)
|   |-- class_e_config.py           # ClassEConfig (overlay)
|   |-- class_f_config.py           # ClassFConfig (classifier)
|-- policy/
|   |-- __init__.py
|   |-- snapshot.py                 # PolicySnapshot, loads from policy doc versions
|   |-- gate_evaluator.py           # GateEvaluator, evaluates report against snapshot
|-- backends/
|   |-- __init__.py
|   |-- protocol.py                 # ValidationBackend protocol
|   |-- mlfinlab_backend.py         # mlfinlab implementation (optional, license-checked)
|   |-- mlfinpy_backend.py          # mlfinpy or equivalent open-source backend
|   |-- internal_backend.py         # In-house DSR/PSR/CPCV implementation
|-- metrics/
|   |-- __init__.py
|   |-- sharpe.py                   # Standard Sharpe, annualized, walk-forward
|   |-- deflated_sharpe.py          # DSR via backend
|   |-- probabilistic_sharpe.py     # PSR via backend
|   |-- information_coefficient.py  # IC for Class A predictions
|   |-- carry_metrics.py            # Class B
|   |-- hedge_metrics.py            # Class C
|   |-- execution_metrics.py        # Class D
|   |-- overlay_metrics.py          # Class E
|   |-- classifier_metrics.py       # Class F
|   |-- conservative_nav.py         # Conservative NAV drawdown, unrealized risk
|   |-- portfolio_contribution.py   # Marginal Sharpe, correlation to existing sleeves
|-- biases/
|   |-- __init__.py
|   |-- suite.py                    # LookaheadTestSuite orchestrating 6 tests
|   |-- timestamp_audit.py          # Test 1: feature.available_at <= prediction_time
|   |-- target_contamination.py     # Test 2: target columns absent from features
|   |-- temporal_permutation.py     # Test 3: shifted-label predictive power collapse
|   |-- embargo_sensitivity.py      # Test 4: increasing embargo doesn't improve Sharpe
|   |-- negative_control.py         # Test 5: planted future feature is detected
|   |-- parity_check.py             # Test 6: research/live feature parity
|   |-- survivorship.py             # Universe-replay test
|   |-- multiple_testing.py         # Bonferroni / Benjamini-Hochberg correction
|-- cpcv/
|   |-- __init__.py
|   |-- label_spec.py               # LabelSpec dataclass
|   |-- purged.py                   # Combinatorial purged CV with proper purging
|   |-- walk_forward.py             # Walk-forward fold generation
|-- cost_model/
|   |-- __init__.py
|   |-- cost_model.py               # CostModel class
|   |-- orderbook_walk.py           # Walk through L2 depth at intended size
|   |-- slippage.py                 # Spread, queue position, market impact
|   |-- fees.py                     # Maker/taker fee schedule
|   |-- funding.py                  # Funding rate accrual
|   |-- stress.py                   # Cost perturbation +/-50%
|-- replay/
|   |-- __init__.py
|   |-- optimizer.py                # PortfolioOptimizer for replay
|   |-- ledger_simulator.py         # Simulated ledger writes during validation
|   |-- nav_computer.py             # NAV from simulated ledger entries
|-- pipelines/
|   |-- __init__.py
|   |-- class_a_predictive.py       # Phase 1 priority -- full implementation
|   |-- class_b_carry.py            # Stub returning NOT_IMPLEMENTED in v0.2
|   |-- class_c_options.py          # Stub
|   |-- class_d_execution.py        # Stub
|   |-- class_e_overlay.py          # Stub
|   |-- class_f_classifier.py       # Stub
|-- reports/
|   |-- __init__.py
|   |-- report.py                   # ValidationReport, GateDecision
|   |-- persistence.py              # Writes to validation.* tables
|   |-- render.py                   # Markdown rendering
|-- tests/
    |-- test_engine.py
    |-- test_metrics.py
    |-- test_bias_suite.py
    |-- test_cost_model.py
    |-- test_cpcv.py
    |-- test_replay.py
    |-- test_pipelines.py
    |-- test_policy_snapshot.py
    |-- test_reproducibility.py
```

External dependencies:
- `numpy`, `pandas`, `scipy.stats` (no version-pin specifics in design; pin in implementation)
- `psycopg` for ledger writes
- `mlfinlab` OPTIONAL via backend protocol; license verification required before commercial use
- `mlfinpy` or equivalent open-source CPCV/DSR/PSR alternative as fallback backend
- No deep learning libraries in Phase 1 (per model_policy v1.1)

## Core types

### ScientificValidationConfig

Inputs determining the scientific result. Same hash -> same metrics, regardless of operator.

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Sequence

class StrategyClass(str, Enum):
    PREDICTIVE_ALPHA = "A"
    CARRY_BASIS = "B"
    OPTIONS_HEDGE_OR_ALPHA = "C"
    EXECUTION_MODEL = "D"
    RISK_OVERLAY = "E"
    SENTIMENT_CLASSIFIER = "F"

@dataclass(frozen=True)
class ScientificValidationConfig:
    strategy_id: int
    strategy_class: StrategyClass
    
    # Artifact identity (hashes, not just paths)
    model_artifact_hash: Optional[str]      # None for non-model strategies
    training_pipeline_hash: Optional[str]   # for retrain-per-fold validation
    feature_set_hash: str
    label_set_hash: str
    data_snapshot_hash: str
    universe_hash: str
    cost_model_hash: str
    
    # Validation window
    start_date: datetime
    end_date: datetime
    
    # CPCV parameters
    walk_forward_train_months: int = 6
    walk_forward_test_months: int = 1
    walk_forward_embargo_weeks: int = 2
    walk_forward_min_folds: int = 6
    cpcv_n_splits: int = 10
    cpcv_embargo_pct: float = 0.02
    
    # Cost stress
    cost_perturbation_range: tuple[float, float] = (0.5, 1.5)
    
    # Bias tests
    bias_tests: Sequence[str] = (
        "timestamp_audit", "target_contamination", "temporal_permutation",
        "embargo_sensitivity", "negative_control", "parity_check",
        "survivorship", "multiple_testing"
    )
    
    # Capacity
    capacity_test_multiples: Sequence[float] = (1.0, 3.0, 10.0)
    intended_deployment_capital_usd: float = 50_000.0
    
    # Policy version binding
    policy_hash: str  # combined hash of all policy doc versions in effect
    
    # Reproducibility
    random_seed: int = 42
    
    # Backend selection (optional override; None means use engine default)
    backend_name: Optional[str] = None
    
    # Computed deterministically from above
    scientific_config_hash: str = ""  # populated post-init via canonical JSON hash
```

The `scientific_config_hash` is computed by canonicalizing this dataclass to JSON and hashing. Two operators running the same scientific validation produce the same hash and (deterministically) the same scientific result.

### ValidationRunMetadata

Run-specific context. Differs across reruns of the same scientific config.

```python
@dataclass(frozen=True)
class ValidationRunMetadata:
    run_id: str                       # UUIDv7
    operator_id: str
    machine_id: str
    code_commit_hash: str             # git commit of validation engine
    engine_version: str
    started_at: datetime
    
    # Computed
    run_metadata_hash: str = ""       # canonical hash of above
```

### Class-specific configs

Each class extends ScientificValidationConfig with class-specific required fields.

```python
@dataclass(frozen=True)
class ClassAConfig(ScientificValidationConfig):
    """Predictive alpha (market-neutral L/S, momentum, mean-reversion)."""
    optimizer_config_hash: str        # PortfolioOptimizer settings
    rebalance_frequency_hours: int = 1
    
    def __post_init__(self):
        assert self.strategy_class == StrategyClass.PREDICTIVE_ALPHA
        assert self.model_artifact_hash is not None
        assert self.training_pipeline_hash is not None

@dataclass(frozen=True)
class ClassBConfig(ScientificValidationConfig):
    """Carry / basis / funding."""
    long_leg_venue: str
    short_leg_venue: str
    hedge_check_frequency_minutes: int = 15
    
    def __post_init__(self):
        assert self.strategy_class == StrategyClass.CARRY_BASIS

# ClassCConfig, ClassDConfig, ClassEConfig, ClassFConfig follow analogously.
```

### ValidationStatus enum

```python
class ValidationStatus(str, Enum):
    PASS = "PASS"                     # Ran fully, all gate criteria passed
    FAIL = "FAIL"                     # Ran fully, one or more gate criteria failed
    INCONCLUSIVE = "INCONCLUSIVE"     # Ran fully, but result confidence below threshold (rare)
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"  # Strategy class pipeline not yet implemented
    NO_DATA = "NO_DATA"               # Required data unavailable; cannot evaluate
    ERROR = "ERROR"                   # Pipeline crashed; investigation required
```

NOT_IMPLEMENTED is the v0.2 corrective for v0.1's NotImplementedError-raising stubs. Classes B-F return ValidationReport with status=NOT_IMPLEMENTED and a clear failure_reasons list explaining the strategy class is not yet validatable.

### GateDecision

```python
@dataclass
class GateDecision:
    gate_name: str                    # e.g., "research_to_shadow"
    status: ValidationStatus
    passed: bool
    failed_criteria: list[str]
    warnings: list[str]
    policy_hash: str                  # which policy version's thresholds were used
    evaluated_at: datetime
```

The decision is computed by `GateEvaluator(report, policy_snapshot)`, separate from the metrics computation. Allows policy revision without code change.

### PolicySnapshot

```python
@dataclass(frozen=True)
class PolicySnapshot:
    """Snapshot of all policy thresholds at a moment in time, by version."""
    
    measurement_policy_version: str
    risk_policy_version: str
    deployment_gates_version: str
    model_policy_version: str
    data_policy_version: str
    allocator_policy_version: str
    incident_severity_policy_version: str
    
    # Class A research-to-shadow thresholds (extracted from model_policy v1.1)
    class_a_walk_forward_sharpe_min: float = 3.0
    class_a_deflated_sharpe_min: float = 0.0
    class_a_probabilistic_sharpe_min: float = 0.95
    class_a_cpcv_median_min: float = 2.5
    class_a_cpcv_min_fold: float = 1.0
    class_a_max_drawdown_pct: float = 15.0          # walk-forward conservative NAV
    class_a_capacity_min_usd: float = 100_000.0
    class_a_survivorship_max_degradation_pct: float = 30.0
    class_a_cost_stress_min_sharpe: float = 1.5
    
    # Class B carry thresholds (extracted from model_policy v1.1)
    class_b_net_carry_min_pct: float = 1.0
    class_b_unwind_cost_max_ratio: float = 0.5      # net carry / unwind cost
    class_b_hedge_stability_min: float = 0.99
    
    # Classes C, D, E, F thresholds (extracted from model_policy v1.1)
    # ... (full list omitted for brevity; same pattern)
    
    # Portfolio contribution thresholds (from allocator_policy v1.0)
    portfolio_correlation_max: float = 0.5          # warn at 0.5
    portfolio_correlation_block: float = 0.7        # block at 0.7
    portfolio_marginal_sharpe_min: float = 0.0      # must contribute non-negatively
    
    # Computed
    policy_hash: str = ""             # canonical hash of all above
```

A `PolicySnapshot` is loaded from policy doc commits. When policies revise, snapshots produce new policy_hash; the validation engine doesn't need code changes.

## ValidationBackend protocol

Abstract interface for DSR/PSR/CPCV computation. Implementations: `mlfinlab_backend`, `mlfinpy_backend`, `internal_backend`.

```python
from typing import Protocol

class ValidationBackend(Protocol):
    """Backend computing DSR, PSR, CPCV. Multiple implementations supported."""
    
    name: str
    version: str
    
    def deflated_sharpe(
        self,
        observed_sr: float,
        sr_estimates: Sequence[float],
        observations: int,
    ) -> float:
        """Deflated Sharpe Ratio (Bailey & Lopez de Prado)."""
        ...
    
    def probabilistic_sharpe(
        self,
        observed_sr: float,
        benchmark_sr: float,
        observations: int,
    ) -> float:
        """Probabilistic Sharpe Ratio."""
        ...
    
    def combinatorial_purged_cv(
        self,
        model_factory: Callable,
        features: pd.DataFrame,
        labels: list[LabelSpec],         # explicit start/end times for purging
        n_splits: int,
        embargo_pct: float,
    ) -> CPCVResults:
        """Combinatorial purged CV with proper label-overlap purging."""
        ...
```

The engine selects a backend at startup. Default order: try `mlfinlab` if license verified and available; fall back to `mlfinpy_backend` (open-source); fall back to `internal_backend` (hand-rolled DSR/PSR with simpler-but-correct CPCV implementation).

License verification for mlfinlab happens at engine startup: looks for a license file or environment variable; if not present, mlfinlab backend is unavailable and engine logs that fallback is in use.

### LabelSpec -- the missing CPCV input

```python
@dataclass(frozen=True)
class LabelSpec:
    instrument_id: int
    prediction_time: datetime
    label_start_time: datetime
    label_end_time: datetime
    target_value: float
    target_type: str                  # 'return', 'rank', 'classification', etc.
```

CPCV uses `label_end_time` for purging: any train sample whose label window overlaps a test sample's label window is purged. This is the v0.2 corrective for v0.1's CPCV pseudo-code which would not purge correctly.

## Bias test suite

Six tests, replacing v0.1's single shuffle-future test.

```python
class LookaheadTestSuite:
    """Six-test suite for lookahead bias detection."""
    
    def __init__(self, model_factory, features, labels, training_pipeline):
        ...
    
    def run(self) -> BiasTestResults:
        return BiasTestResults(
            timestamp_audit=self._test_timestamp_audit(),
            target_contamination=self._test_target_contamination(),
            temporal_permutation=self._test_temporal_permutation(),
            embargo_sensitivity=self._test_embargo_sensitivity(),
            negative_control=self._test_negative_control(),
            parity_check=self._test_parity_check(),
        )
    
    def _test_timestamp_audit(self) -> BiasTestResult:
        """For every feature value, assert feature.available_at <= label.prediction_time."""
        ...
    
    def _test_target_contamination(self) -> BiasTestResult:
        """Assert no column in features matches a target column by name or values."""
        ...
    
    def _test_temporal_permutation(self) -> BiasTestResult:
        """Shift labels by +/-N periods; predictive power should collapse."""
        ...
    
    def _test_embargo_sensitivity(self) -> BiasTestResult:
        """Increase embargo from baseline to 4x; Sharpe should not materially improve.
        Improvement indicates leakage was being suppressed by short embargo."""
        ...
    
    def _test_negative_control(self) -> BiasTestResult:
        """Inject a deliberately leaky feature (future_return_1d). Test should detect it."""
        ...
    
    def _test_parity_check(self) -> BiasTestResult:
        """Same instrument, same timestamp: research feature value == live feature value.
        Failure means research and production paths diverge -- strategy can pass research
        but fail live for reasons invisible to validation."""
        ...
```

Pass criterion for the suite: all six tests pass. A single failure is sufficient to fail the gate. The negative_control test specifically failing (i.e., not catching the planted leak) means the suite itself is broken -- engine logs ENGINE_INTEGRITY_FAILURE and refuses to validate any strategy until the bias-test infrastructure is repaired.

## Class A pipeline (predictive alpha) -- the Phase 1 priority

```python
def class_a_predictive_pipeline(
    config: ClassAConfig,
    run_metadata: ValidationRunMetadata,
    ledger: LedgerClient,
    cost_model: CostModel,
    feature_store: FeatureStore,
    backend: ValidationBackend,
    policy_snapshot: PolicySnapshot,
    portfolio_optimizer: PortfolioOptimizer,
    ledger_simulator: LedgerSimulator,
) -> ValidationReport:
    
    report = ValidationReport(
        scientific_config=config,
        run_metadata=run_metadata,
        status=ValidationStatus.ERROR,  # default; overwritten on completion
    )
    
    try:
        # 1. Verify config and policy hashes
        if config.scientific_config_hash != compute_hash(config):
            report.status = ValidationStatus.ERROR
            report.failure_reasons.append("scientific_config_hash mismatch")
            return report
        
        # 2. Verify all data sources VERIFIED per measurement_policy
        unverified = ledger.find_unverified_sources(
            config.feature_set_hash, config.data_snapshot_hash
        )
        if unverified:
            report.status = ValidationStatus.NO_DATA
            report.failure_reasons.append(f"unverified sources: {unverified}")
            return report
        
        # 3. Verify L2 data available per deployment_gates v1.1 prerequisite
        if not ledger.l2_data_verified_for_window(
            config.start_date, config.end_date, config.universe
        ):
            report.status = ValidationStatus.NO_DATA
            report.failure_reasons.append(
                "L2 data not VERIFIED for validation window"
            )
            return report
        
        # 4. Load training pipeline and labels
        training_pipeline = load_training_pipeline_artifact(
            config.training_pipeline_hash
        )
        labels = feature_store.load_labels(config.label_set_hash)
        features = feature_store.load_features(
            feature_set_hash=config.feature_set_hash,
            universe_hash=config.universe_hash,
            start=config.start_date,
            end=config.end_date,
        )
        
        # 5. Generate walk-forward folds
        folds = generate_walk_forward_folds(
            features, labels,
            train_months=config.walk_forward_train_months,
            test_months=config.walk_forward_test_months,
            embargo_weeks=config.walk_forward_embargo_weeks,
        )
        
        if len(folds) < config.walk_forward_min_folds:
            report.status = ValidationStatus.FAIL
            report.failure_reasons.append(
                f"Insufficient folds: {len(folds)} < "
                f"{config.walk_forward_min_folds}"
            )
            return report
        
        # 6. Walk-forward: retrain per fold via training pipeline (v0.2 fix)
        fold_returns = []
        fold_results = []
        for fold_idx, fold in enumerate(folds):
            # Retrain per fold -- validates the training pipeline,
            # not just one frozen model
            fold_model = training_pipeline.train(
                fold.train_features, fold.train_labels
            )
            fold_predictions = fold_model.predict(fold.test_features)
            
            # Predictions -> optimizer -> orders (v0.2 addition)
            target_weights = portfolio_optimizer.solve(
                predictions=fold_predictions,
                universe=config.universe,
                constraints=policy_snapshot.allocator_constraints(),
            )
            order_intents = generate_order_intents(
                current_positions=fold.start_positions,
                target_weights=target_weights,
            )
            
            # Orders -> cost-modeled fills (v0.2 addition)
            fills = cost_model.simulate_fills(
                order_intents=order_intents,
                orderbook_l2=fold.test_orderbook_l2,
            )
            
            # Fills -> ledger entries -> NAV -> returns (v0.2 addition)
            ledger_simulator.apply_fills(fills)
            ledger_simulator.apply_funding(fold.test_funding_payments)
            ledger_simulator.mark_positions(fold.test_marks)
            nav_series = ledger_simulator.compute_nav_snapshots()
            fold_return_series = ledger_simulator.compute_twr_returns(
                nav_series
            )
            
            fold_returns.append(fold_return_series)
            fold_results.append(FoldResult(
                fold_id=fold_idx,
                train_start=fold.train_start,
                train_end=fold.train_end,
                test_start=fold.test_start,
                test_end=fold.test_end,
                sharpe=annualized_sharpe(fold_return_series),
                drawdown=max_drawdown(nav_series),
                turnover=compute_turnover(
                    target_weights, fold.start_positions
                ),
                cost_bps=compute_realized_cost_bps(fills),
            ))
        
        report.fold_results = fold_results
        combined_returns = pd.concat(fold_returns)
        report.walk_forward_sharpe = annualized_sharpe(combined_returns)
        
        # 7. Conservative NAV metrics (v0.2 addition)
        report.conservative_nav_max_drawdown_pct = max_drawdown_pct(
            nav_series
        )
        report.max_unrealized_loss_pct = max_unrealized_loss(
            ledger_simulator
        )
        report.max_open_inventory_pct = max_open_inventory_pct(
            ledger_simulator
        )
        report.forced_exit_slippage_p95 = compute_forced_exit_slippage(
            ledger_simulator, percentile=95
        )
        
        # 8. Backend metrics (DSR, PSR via abstraction)
        report.deflated_sharpe = backend.deflated_sharpe(
            observed_sr=report.walk_forward_sharpe,
            sr_estimates=[r.sharpe for r in fold_results],
            observations=len(combined_returns),
        )
        report.probabilistic_sharpe = backend.probabilistic_sharpe(
            observed_sr=report.walk_forward_sharpe,
            benchmark_sr=1.0,
            observations=len(combined_returns),
        )
        
        # 9. CPCV with proper label end-times
        cpcv_results = backend.combinatorial_purged_cv(
            model_factory=lambda: training_pipeline.train_factory(),
            features=features,
            labels=labels,
            n_splits=config.cpcv_n_splits,
            embargo_pct=config.cpcv_embargo_pct,
        )
        report.cpcv_fold_sharpes = cpcv_results.fold_sharpes
        report.cpcv_median = float(np.median(cpcv_results.fold_sharpes))
        
        # 10. Bias test suite (six tests)
        bias_suite = LookaheadTestSuite(
            training_pipeline=training_pipeline,
            features=features,
            labels=labels,
            embargo_baseline_weeks=config.walk_forward_embargo_weeks,
        )
        report.bias_test_results = bias_suite.run()
        report.lookahead_test_passed = (
            report.bias_test_results.all_passed()
        )
        
        # 11. Survivorship test
        report.survivorship_test_sharpe_degradation = (
            run_survivorship_test(
                training_pipeline, config.universe_hash,
                config.start_date, config.end_date,
            )
        )
        
        # 12. Multiple-testing correction
        report.multiple_testing_surviving_factors = (
            run_multiple_testing_correction(
                features.columns, alpha=0.05,
                method="benjamini_hochberg",
            )
        )
        
        # 13. Cost stress (return perturbation in v0.2;
        #     full fill re-simulation in v0.3)
        report.cost_stress_min_sharpe = run_cost_stress(
            combined_returns, cost_model,
            perturbation_range=config.cost_perturbation_range,
        )
        # NOTE: v0.2 limitation -- cost stress perturbs returns rather
        # than re-simulating the full order -> fill chain. v0.3 will
        # upgrade to full fill re-simulation.
        
        # 14. Capacity test
        capacity_results = run_capacity_test(
            training_pipeline=training_pipeline,
            features=features,
            universe=config.universe,
            cost_model=cost_model,
            capital_multiples=config.capacity_test_multiples,
            base_capital=config.intended_deployment_capital_usd,
        )
        report.capacity_estimate_usd = (
            capacity_results.max_capital_no_degradation
        )
        report.sharpe_at_3x_capital = capacity_results.sharpe_at_3x
        
        # 15. Portfolio contribution metrics (v0.2 addition)
        active_strategies = ledger.find_active_strategies(
            exclude=[config.strategy_id]
        )
        if active_strategies:
            portfolio_contribution = compute_portfolio_contribution(
                strategy_returns=combined_returns,
                active_strategy_returns=ledger.fetch_strategy_returns(
                    active_strategies
                ),
                stress_window_days=ledger.find_stress_windows(
                    config.start_date, config.end_date
                ),
            )
            report.portfolio_sharpe_with_strategy = (
                portfolio_contribution.sharpe_with
            )
            report.portfolio_sharpe_without_strategy = (
                portfolio_contribution.sharpe_without
            )
            report.marginal_sharpe_contribution = (
                portfolio_contribution.marginal_sharpe
            )
            report.marginal_es_contribution = (
                portfolio_contribution.marginal_expected_shortfall
            )
            report.correlation_to_existing_sleeves = (
                portfolio_contribution.correlations
            )
            report.crisis_correlation = (
                portfolio_contribution.crisis_correlation
            )
            report.co_drawdown_score = (
                portfolio_contribution.co_drawdown_score
            )
        else:
            # Phase 1 single-engine case: portfolio contribution
            # not applicable
            report.portfolio_contribution_applicable = False
        
        # 16. Gate decision via PolicySnapshot
        #     (v0.2 -- thresholds not hard-coded)
        gate_evaluator = GateEvaluator(policy_snapshot)
        gate_decision = gate_evaluator.evaluate(
            report, gate_name="research_to_shadow"
        )
        report.gate_decisions.append(gate_decision)
        report.status = (
            ValidationStatus.PASS if gate_decision.passed
            else ValidationStatus.FAIL
        )
        
    except NoDataError as e:
        report.status = ValidationStatus.NO_DATA
        report.failure_reasons.append(str(e))
    except Exception as e:
        report.status = ValidationStatus.ERROR
        report.failure_reasons.append(
            f"unexpected error: {type(e).__name__}: {e}"
        )
        # Re-raise after recording so caller knows engine had
        # unexpected issue
        ledger_simulator.persist_failed_run(report)
        raise
    finally:
        report.completed_at = now()
        ledger_simulator.persist_validation_report(report)
    
    return report
```

Key v0.2 additions vs v0.1:
- Retrain per fold (line 6) -- validates training pipeline, not just frozen model
- Portfolio optimizer integration (line 6 sub-step) -- predictions don't directly become returns
- Ledger simulator (line 6 sub-step) -- simulated fills become simulated ledger entries become NAV
- Conservative NAV metrics (step 7) -- open positions visible to validation
- LabelSpec for CPCV (step 9) -- proper purging
- Bias test suite (step 10) -- six tests, not one shuffle
- Portfolio contribution (step 15) -- marginal Sharpe, correlation to existing sleeves
- GateEvaluator + PolicySnapshot (step 16) -- thresholds in policy, not code

## Classes B-F pipelines

In v0.2, Classes B-F have full interface support but pipelines return ValidationStatus.NOT_IMPLEMENTED.

```python
def class_b_carry_pipeline(
    config: ClassBConfig,
    run_metadata: ValidationRunMetadata,
    ...
) -> ValidationReport:
    report = ValidationReport(
        scientific_config=config,
        run_metadata=run_metadata,
        status=ValidationStatus.NOT_IMPLEMENTED,
    )
    report.failure_reasons.append(
        "Class B carry pipeline not implemented in v0.2. "
        "Implementation deferred until carry engine enters scoping "
        "(Phase 7+ per SuperHydra plan). "
        "Strategy registered in this class cannot advance to Shadow "
        "until pipeline is implemented."
    )
    report.completed_at = now()
    return report
```

The Class B-F config classes and report fields exist; only the pipeline implementations are stubs. This is the v0.2 corrective for v0.1's contradiction (was simultaneously claimed to "support all six classes from day one" and "stubbed in Phase 1 raising NotImplementedError").

## Validation schema (separate from registry)

v0.2 introduces a `validation` schema. The single `registry.validation_reports` table from v0.3 ledger-schema patch is replaced with the more comprehensive set below.

```sql
CREATE SCHEMA validation;

CREATE TABLE validation.policy_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    policy_hash TEXT NOT NULL UNIQUE,
    measurement_policy_version TEXT NOT NULL,
    risk_policy_version TEXT NOT NULL,
    deployment_gates_version TEXT NOT NULL,
    model_policy_version TEXT NOT NULL,
    data_policy_version TEXT NOT NULL,
    allocator_policy_version TEXT NOT NULL,
    incident_severity_policy_version TEXT NOT NULL,
    snapshot_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE validation.reports (
    id UUID NOT NULL DEFAULT gen_uuidv7() PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES registry.strategies(id),
    model_id BIGINT REFERENCES registry.models(id),
    portfolio_id BIGINT REFERENCES registry.portfolios(id),
    
    strategy_class CHAR(1) NOT NULL
        CHECK (strategy_class IN ('A','B','C','D','E','F')),
    
    -- Reproducibility hashes
    scientific_config_hash TEXT NOT NULL,
    scientific_result_hash TEXT NOT NULL,
    run_metadata_hash TEXT NOT NULL,
    
    -- Engine and policy provenance
    engine_version TEXT NOT NULL,
    code_commit_hash TEXT NOT NULL,
    policy_snapshot_id BIGINT NOT NULL
        REFERENCES validation.policy_snapshots(id),
    
    -- Artifact integrity
    model_artifact_hash TEXT,
    training_pipeline_hash TEXT,
    feature_set_hash TEXT NOT NULL,
    label_set_hash TEXT NOT NULL,
    data_snapshot_hash TEXT NOT NULL,
    cost_model_hash TEXT NOT NULL,
    universe_hash TEXT NOT NULL,
    
    -- Backend used
    backend_name TEXT NOT NULL,
    backend_version TEXT NOT NULL,
    
    -- Environment classification per measurement_policy v1.1
    validation_environment TEXT NOT NULL CHECK (
        validation_environment IN (
            'BACKTEST', 'REPLAY', 'SHADOW', 'CANARY_REVIEW'
        )
    ),
    settlement_type TEXT NOT NULL CHECK (
        settlement_type IN (
            'SIMULATED_FILL', 'MODELED_FILL', 'LIVE_CONFIRMED'
        )
    ),
    
    -- Top-line metrics (extracted for fast queries)
    walk_forward_sharpe NUMERIC(20,12),
    deflated_sharpe NUMERIC(20,12),
    probabilistic_sharpe NUMERIC(20,12),
    cpcv_median NUMERIC(20,12),
    cpcv_min_fold NUMERIC(20,12),
    capacity_estimate_usd NUMERIC(38,12),
    conservative_nav_max_drawdown_pct NUMERIC(20,12),
    cost_stress_min_sharpe NUMERIC(20,12),
    
    -- Portfolio contribution
    marginal_sharpe_contribution NUMERIC(20,12),
    crisis_correlation NUMERIC(20,12),
    
    -- Status and gate
    status TEXT NOT NULL CHECK (status IN (
        'PASS', 'FAIL', 'INCONCLUSIVE',
        'NOT_IMPLEMENTED', 'NO_DATA', 'ERROR'
    )),
    research_to_shadow_pass BOOLEAN NOT NULL,
    failure_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    
    -- Full data
    full_report JSONB NOT NULL,
    
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    operator_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE (
        strategy_id, scientific_config_hash,
        engine_version, policy_snapshot_id
    )
);

CREATE INDEX idx_validation_strategy
    ON validation.reports(strategy_id, completed_at DESC);
CREATE INDEX idx_validation_passed
    ON validation.reports(strategy_id)
    WHERE research_to_shadow_pass = TRUE;
CREATE INDEX idx_validation_status
    ON validation.reports(status, completed_at DESC);
CREATE INDEX idx_validation_class
    ON validation.reports(strategy_class, completed_at DESC);

CREATE TABLE validation.fold_metrics (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL
        REFERENCES validation.reports(id) ON DELETE CASCADE,
    fold_id INTEGER NOT NULL,
    train_start TIMESTAMPTZ NOT NULL,
    train_end TIMESTAMPTZ NOT NULL,
    test_start TIMESTAMPTZ NOT NULL,
    test_end TIMESTAMPTZ NOT NULL,
    sharpe NUMERIC(20,12),
    drawdown_pct NUMERIC(20,12),
    turnover NUMERIC(20,12),
    cost_bps NUMERIC(20,12),
    fold_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fold_metrics_report
    ON validation.fold_metrics(report_id);

CREATE TABLE validation.bias_test_results (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL
        REFERENCES validation.reports(id) ON DELETE CASCADE,
    test_name TEXT NOT NULL CHECK (test_name IN (
        'timestamp_audit', 'target_contamination',
        'temporal_permutation', 'embargo_sensitivity',
        'negative_control', 'parity_check',
        'survivorship', 'multiple_testing'
    )),
    result TEXT NOT NULL CHECK (
        result IN ('pass', 'fail', 'warning', 'not_run')
    ),
    metric_value NUMERIC(20,12),
    threshold NUMERIC(20,12),
    details JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_bias_test_report
    ON validation.bias_test_results(report_id);
CREATE INDEX idx_bias_test_failures
    ON validation.bias_test_results(test_name, created_at DESC)
    WHERE result = 'fail';

CREATE TABLE validation.artifacts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL
        REFERENCES validation.reports(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN (
        'model', 'training_pipeline', 'feature_matrix',
        'labels', 'returns', 'fold_assignments',
        'cost_model', 'plot', 'markdown_report', 'config'
    )),
    artifact_path TEXT NOT NULL,
    artifact_hash TEXT NOT NULL,
    artifact_size_bytes BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_artifacts_report
    ON validation.artifacts(report_id);

CREATE TABLE validation.cost_model_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL
        REFERENCES validation.reports(id) ON DELETE CASCADE,
    cost_model_hash TEXT NOT NULL,
    perturbation_factor NUMERIC(10,4) NOT NULL,
    sharpe_at_perturbation NUMERIC(20,12),
    realized_cost_bps NUMERIC(20,12),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE validation.capacity_tests (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL
        REFERENCES validation.reports(id) ON DELETE CASCADE,
    capital_multiple NUMERIC(10,4) NOT NULL,
    capital_usd NUMERIC(38,12) NOT NULL,
    sharpe_at_size NUMERIC(20,12),
    slippage_bps NUMERIC(20,12),
    fill_rate NUMERIC(10,8),
    market_impact_bps NUMERIC(20,12),
    binding_constraint TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE validation.reproductions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    original_report_id UUID NOT NULL
        REFERENCES validation.reports(id),
    reproduction_report_id UUID NOT NULL
        REFERENCES validation.reports(id),
    scientific_result_match BOOLEAN NOT NULL,
    discrepancies JSONB NOT NULL DEFAULT '[]'::jsonb,
    reproduced_by TEXT NOT NULL,
    reproduced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reproductions_original
    ON validation.reproductions(original_report_id);
```

This schema supersedes the single `registry.validation_reports` table that v0.3 ledger schema patch added. The ledger v0.4 will note this migration: `registry.validation_reports` deprecated in favor of `validation.*` schema.

## Reproducibility primitives

Three rules:

1. **Scientific result determinism.** Same `scientific_config_hash` + same `engine_version` + same `policy_hash` + same data snapshot -> identical `scientific_result_hash`. Verified by `engine.reproduce(report_id)` which re-runs and compares scientific results, ignoring run metadata (timestamps, run_id, operator_id, machine_id).

2. **Backend version pinned via policy.** The validation engine's choice of backend (mlfinlab/mlfinpy/internal) is part of the engine_version. Backend updates require explicit operator promotion and full re-validation of currently-deployed models.

3. **No global state.** Pipelines are pure functions of config and data. No module-level mutable state. Random seeds drawn from `scientific_config_hash` so determinism holds across machines.

## Acceptance criteria for Phase 1 implementation (v0.2)

The validation engine is considered complete when ALL fifteen of the following pass:

1. **Class A pipeline runnable end-to-end** on a toy strategy -- produces complete ValidationReport with all metrics computed
2. **Reproducibility test passes:** running the same scientific config twice produces identical `scientific_result_hash`
3. **Bias suite rejects leaky model:** deliberately leaky test model fails the lookahead suite (specifically the negative_control test catches it)
4. **Backend abstraction works:** engine runs successfully with mlfinpy_backend even when mlfinlab is unavailable
5. **Cost model integration verified:** cost stress sensitivity correctly perturbs the underlying cost model
6. **Ledger persistence verified:** report writes to `validation.reports` and related tables with correct schema; foreign keys resolve correctly
7. **Empty-source safety verified:** running with empty L2 data raises `NoDataError` per measurement_policy; report status is NO_DATA, not ERROR
8. **Policy snapshot test:** changing model_policy threshold (via different PolicySnapshot) changes gate decision without changing engine code
9. **Artifact hash test:** modifying model artifact after validation causes reproduction to fail with explicit hash-mismatch error
10. **Fold leakage test:** intentionally overlapping labels are purged from train folds (CPCV correctness)
11. **Optimizer integration test:** Class A pipeline replays through optimizer -> orders -> simulated fills -> ledger NAV, not just predictions -> returns
12. **Conservative NAV test:** open positions with adverse marks reduce validation conservative-NAV drawdown even when realized fills are positive
13. **Strategy-class lockout test:** Classes B-F return ValidationStatus.NOT_IMPLEMENTED and cannot advance to Shadow
14. **Report immutability test:** validation.reports rows cannot be edited after persistence; corrections create superseding reports linked via reproductions table
15. **Portfolio contribution test:** when other strategies are active, a standalone-profitable strategy that worsens portfolio expected shortfall fails or receives warning per allocator_policy thresholds

These fifteen criteria are the gate from validation-engine-complete to ready-to-validate-strategies.

## Open design questions deferred to implementation

1. **Cost stress upgrade to full fill re-simulation.** v0.2 uses return-perturbation (perturb realized returns by +/-50%) as a shortcut. v0.3 will upgrade to re-running the full `orders -> L2 walk -> fills -> ledger -> returns` chain at perturbed cost parameters. This matters because cost changes can affect which orders fill, partial fills, optimizer rebalance timing, and turnover. Documented as known limitation in v0.2.

2. **Parallelization of folds and CPCV.** Each fold and CPCV split is independent; can run in parallel. Phase 1 implementation may defer parallelization. Quantify time cost vs implementation cost during Phase 1 weeks 5-6.

3. **Caching of deterministic intermediate results.** Model predictions on identical (model, features) inputs are deterministic. Caching could speed up reproducibility tests by 10x+. Defer until validation runs become a bottleneck.

4. **Visualization beyond markdown.** `reports/render.py` produces markdown in v0.2; later may add HTML/PDF/dashboard. Phase 1 markdown is sufficient.

5. **Class B carry pipeline implementation.** Reviewer suggested implementing Class B early since it's mechanically tractable without mlfinlab. v0.2 keeps it as NOT_IMPLEMENTED stub; full implementation deferred to when carry engine enters scoping per SuperHydra plan (Phase 7+). Premature implementation would expand Phase 1 scope.

6. **Live cost model retraining governance.** The cost model itself drifts and may need quarterly retraining against realized fills. Defer governance to model_policy v1.2 if observed in Phase 4 shadow run.

7. **Cross-strategy validation runs.** When multiple strategies validate concurrently, portfolio contribution metrics depend on each other. Resolve via "snapshot of currently-active strategies at validation start" -- each strategy's validation uses the snapshot, no race condition.

## Migration note for Phase 1 implementation

Phase 1 implementation builds the validation engine fresh against this v0.2 design. No migration from v0.1 needed since v0.1 was a design doc, not deployed code.

The Phase 1 ledger schema must include the `validation.*` schema and tables specified above. The single `registry.validation_reports` table from ledger v0.3 patch is superseded -- implementation should create the full validation schema instead.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-05-02 | Wasseem Katt | Initial design -- Class A pipeline sketch, single mlfinlab backend, single shuffle lookahead test, hard-coded thresholds, predictions-to-returns flow |
| 0.2 | 2026-05-02 | Wasseem Katt | Major restructuring: ValidationBackend protocol replacing mlfinlab hard-dependency; LabelSpec for proper CPCV purging; six-test lookahead suite replacing single shuffle; PolicySnapshot for non-hard-coded thresholds; artifact hashes replacing path-only references; split scientific_config_hash from run_metadata_hash; full optimizer + ledger simulator integration; portfolio contribution metrics; conservative NAV metrics; ValidationStatus enum (PASS/FAIL/INCONCLUSIVE/NOT_IMPLEMENTED/NO_DATA/ERROR); GateDecision separate from metrics; class-specific configs; walk-forward retrains per fold from training pipeline; validation schema separate from registry with 7 tables; 8 additional acceptance criteria; cost stress as return-perturbation in v0.2 with v0.3 roadmap to full fill re-simulation; Classes B-F as NOT_IMPLEMENTED interfaces rather than exception-raising stubs |

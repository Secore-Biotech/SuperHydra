# OMS Skeleton Design v0.2

**Status:** Initial committed design (v0.1 drafted, never committed; v0.2 incorporates external review)
**Author:** Wasseem Katt
**Date:** 2026-05-02
**Implements:** measurement_policy.md v1.1 sections 7-8 (atomic order recording, promotion-gated execution); risk_policy.md v1.1 sections 6, 9-10 (pre-trade check sequence, kill switches, override procedure); incident_severity_policy.md v1.0 (P0 auto-trigger conditions); deployment_gates.md v1.1 (paper-via-OMS for Shadow); allocator_policy.md v1.0 (target weights to order intents); model_policy.md v1.1 strategy classes
**Implementation target:** Phase 1 (May 11 - June 15 2026), specifically Phase 1 weeks 7-9 per the SuperHydra Enhanced Plan
**Related:** ledger schema v0.3, validation engine design v0.2

This document specifies the Order Management System that gates every order in SuperHydra. Without this OMS, the policy enforcement is at the discretion of strategy code; with it, enforcement is architectural.

## Why v0.2 (and why v0.1 was not committed)

v0.1 contained three safety-critical bugs that would have caused real production incidents:

1. **client_order_id minute-boundary bug.** v0.1 included `YYYYMMDDHHMM` in the client_order_id. A retry of the same intent across a minute boundary produced a different ID, defeating the entire idempotency guarantee. v0.2 derives client_order_id from immutable intent data only.

2. **Float types for monetary values.** v0.1 used `float` for quantities, prices, and exposures. Float rounding errors produce venue rejections (tick-size violations) and position drift. v0.2 uses `Decimal` throughout, with explicit instrument-rule normalization before adapter submission.

3. **Adapters writing to ledger.** v0.1 had both OMS and adapter writing order status; PaperAdapter wrote fills directly. Mixed ownership creates race conditions and audit-trail ambiguity. v0.2 enforces: adapters do venue I/O only; OMS and Reconciler own all ledger writes.

In addition to those three, v0.2 incorporates 14 further improvements: deterministic L2 snapshot IDs for paper reproducibility, advisory lock for concurrent-approval safety, unknown-submit recovery flow, execution_environment / settlement_type on OrderIntent, order_group_id for multi-leg support, exposure reservations, DB-backed outbox queue, kill-switch action plans, venue capability registry, instrument-rule normalization, self-cross checks, unknown venue order auto-action, fast-fail skipped-check reporting, and corrected "atomic" wording.

## Architectural rules (the seven things this OMS makes impossible)

The OMS exists to make HYDRA's failure classes structurally impossible. Each rule below is enforced architecturally, not by discipline:

1. **No code path reaches a venue except through the OMS.** Strategy -> Allocator -> Risk Kernel -> OMS -> Adapter -> Reconciler -> Ledger. Direct venue API calls are forbidden by file structure: only the OMS module imports adapter modules.

2. **Every order has a stable, idempotent client_order_id.** Derived from immutable intent data only. Retries hit the database UNIQUE constraint or the venue's own idempotency, never produce duplicates.

3. **Every order passes risk kernel pre-trade checks.** No bypass paths exist. Even REPL trades route through OMS.

4. **Every order requires a current strategy promotion event.** The promotion event also encodes execution_environment (RESEARCH/SHADOW/CANARY/SCALE/REPL); StrategyPromotedCheck rejects intents whose environment doesn't match the strategy's current promotion phase.

5. **Every order writes to the ledger before any venue call.** Durable write-ahead, not "atomic" -- true atomicity with an external venue is impossible. Correctness is achieved through write-ahead recording, deterministic client_order_id, unknown-submit recovery, and reconciliation.

6. **Reconciler runs continuously.** Venue <-> ledger discrepancies are detected within 60 seconds. Discrepancies unresolved beyond 5 minutes auto-trigger PORTFOLIO_HALT.

7. **Paper adapter and live adapter share interface.** Strategy code cannot tell them apart. The PaperAdapter is deterministic given the same L2 snapshot ID and cost model hash -- shadow runs are reproducible.

## Module structure

```
hydra-next/execution/
|-- __init__.py
|-- oms/
|   |-- __init__.py
|   |-- intent.py                 # OrderIntent dataclass with Decimal fields
|   |-- order.py                  # Order dataclass and state machine
|   |-- client_id.py              # Stable idempotent client_order_id (no time component)
|   |-- submitter.py              # Submission orchestration with advisory lock
|   |-- canceler.py               # Cancellation with priority handling
|   |-- state_machine.py          # OrderStatus transitions and validation
|   |-- reservations.py           # Exposure / cash / margin reservation manager
|   |-- outbox.py                 # DB-backed transactional outbox
|   |-- instrument_rules.py       # tick_size / lot_size / min_notional normalization
|   |-- exceptions.py             # OMS-specific errors
|-- risk_kernel/
|   |-- __init__.py
|   |-- kernel.py                 # RiskKernel.evaluate(intent) -> decision
|   |-- snapshot.py               # PortfolioSnapshot with snapshot_id and risk_version
|   |-- advisory_lock.py          # Postgres advisory lock per portfolio_id
|   |-- checks/
|   |   |-- __init__.py
|   |   |-- system_health.py      # require_system_healthy
|   |   |-- venue_allowed.py      # require_venue_allowed + venue_capability check
|   |   |-- strategy_promoted.py  # require_strategy_promoted + environment match
|   |   |-- data_fresh.py         # require_data_fresh
|   |   |-- reconciliation.py     # require_no_reconciliation_break
|   |   |-- edge_vs_cost.py       # require_expected_edge_gt_2x_cost
|   |   |-- liquidity_volume.py   # require_daily_volume_liquidity
|   |   |-- liquidity_depth.py    # require_orderbook_depth_sufficient
|   |   |-- liquidity_exit.py     # require_exit_liquidity_sufficient
|   |   |-- liquidity_stress.py   # require_stress_exit_cost_within_budget
|   |   |-- position_limit.py     # require_position_limit
|   |   |-- cluster_limit.py      # require_cluster_limit
|   |   |-- net_exposure.py       # require_net_exposure_limit
|   |   |-- gross_exposure.py     # require_gross_exposure_limit
|   |   |-- beta_limit.py         # require_beta_limit
|   |   |-- funding_limit.py      # require_funding_limit
|   |   |-- margin_limit.py       # require_margin_limit
|   |   |-- drawdown_state.py     # require_drawdown_state_allows_risk
|   |   |-- strategy_constraints.py  # require_strategy_constraints_met
|   |   |-- self_cross.py         # require_no_self_cross (v0.2 addition)
|   |   |-- conflicting_order.py  # require_no_conflicting_open_order (v0.2 addition)
|   |   |-- kill_switch.py        # require_kill_switch_clear
|   |-- decision.py               # RiskDecision + RiskCheckResult dataclasses
|-- adapters/
|   |-- __init__.py
|   |-- protocol.py               # VenueAdapter Protocol -- venue I/O only
|   |-- capabilities.py           # VenueCapabilities registry
|   |-- paper_adapter.py          # PaperAdapter, deterministic given L2 snapshot ID
|   |-- binance_futures_adapter.py # Live Binance Futures
|   |-- adapter_registry.py       # Maps venue_id -> adapter instance
|-- reconciler/
|   |-- __init__.py
|   |-- reconciler.py             # Continuous reconciler loop
|   |-- checks/
|   |   |-- __init__.py
|   |   |-- orders.py             # Local orders vs venue orders
|   |   |-- fills.py              # Local fills vs venue fills + auto-import
|   |   |-- positions.py          # Local positions vs venue positions
|   |   |-- balances.py           # Local cash vs venue cash
|   |   |-- margin.py             # Margin state consistency
|   |   |-- funding.py            # Funding payment reconciliation
|   |   |-- unknown_orders.py     # Auto-action on venue orders not in ledger (v0.2)
|   |-- break_handler.py          # Logs to risk.reconciliation_breaks
|   |-- auto_actions.py           # Auto-trigger PORTFOLIO_HALT after 5min unresolved
|-- kill_switch/
|   |-- __init__.py
|   |-- manager.py                # KillSwitchManager (engage / release / status)
|   |-- action_plans.py           # Concrete cancel/halt action plans (v0.2 addition)
|   |-- auto_triggers.py          # Auto-engagement per incident_severity_policy
|-- audit/
|   |-- __init__.py
|   |-- flag_changes.py           # Logs to audit.flag_audit_log
|-- tests/
    |-- test_oms.py
    |-- test_risk_kernel.py
    |-- test_adapters.py
    |-- test_reconciler.py
    |-- test_kill_switch.py
    |-- test_idempotency.py
    |-- test_decimal_precision.py     # v0.2 addition
    |-- test_concurrent_approval.py   # v0.2 addition
    |-- test_unknown_submit.py        # v0.2 addition
    |-- test_paper_determinism.py     # v0.2 addition
    |-- test_capability_registry.py   # v0.2 addition
```

## Core types

### OrderIntent

```python
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Literal
from uuid import UUID

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LIMIT = "stop_limit"
    STOP_MARKET = "stop_market"

class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTD = "GTD"

class ExecutionEnvironment(str, Enum):
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    SCALE = "SCALE"
    REPL = "REPL"

class SettlementType(str, Enum):
    SIMULATED_FILL = "SIMULATED_FILL"
    MODELED_FILL = "MODELED_FILL"
    LIVE_CONFIRMED = "LIVE_CONFIRMED"

class GroupRole(str, Enum):
    SINGLE = "single"
    PARENT = "parent"
    CHILD = "child"
    HEDGE_LEG = "hedge_leg"
    REBALANCE_LEG = "rebalance_leg"
    FLATTEN_LEG = "flatten_leg"

class ContingencyType(str, Enum):
    NONE = "none"
    ALL_OR_CANCEL = "all_or_cancel"
    BEST_EFFORT = "best_effort"
    SEQUENTIAL = "sequential"
    HEDGE_REQUIRED = "hedge_required"

@dataclass(frozen=True)
class OrderIntent:
    intent_uuid: UUID
    strategy_id: int
    portfolio_id: int
    venue_id: int
    account_id: int
    instrument_id: int

    # Quantities and prices: Decimal, never float (v0.2 fix)
    side: OrderSide
    quantity: Decimal
    price: Optional[Decimal]                # None for market orders
    order_type: OrderType
    time_in_force: TimeInForce
    post_only: bool = False
    reduce_only: bool = False

    # Provenance -- full chain to allocator and signal
    allocator_run_id: Optional[UUID] = None
    signal_batch_id: Optional[UUID] = None
    target_weight_id: Optional[UUID] = None
    rebalance_id: Optional[UUID] = None

    # Multi-leg / grouping support (v0.2 addition)
    order_group_id: Optional[UUID] = None
    group_role: GroupRole = GroupRole.SINGLE
    contingency_type: ContingencyType = ContingencyType.NONE

    # Execution context (v0.2 -- ties to measurement_policy v1.1)
    execution_environment: ExecutionEnvironment
    settlement_type: SettlementType

    # Cost model expectations (Decimal, v0.2 fix)
    expected_edge_bps: Optional[Decimal] = None
    expected_slippage_bps: Optional[Decimal] = None
    expected_funding_bps: Optional[Decimal] = None
    confidence: Optional[Decimal] = None
    horizon_minutes: Optional[int] = None

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
```

The intent is immutable. Once created, fields never change. All monetary values are Decimal -- float is forbidden by both code review and unit tests that assert no float in any monetary field path.

### Order

Identical to v0.1 in shape but with Decimal fields and additional grouping fields. Stored in `trading.orders` per ledger schema v0.3.

```python
class OrderStatus(str, Enum):
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    STALE_NEEDS_RECONCILIATION = "STALE_NEEDS_RECONCILIATION"
    UNKNOWN = "UNKNOWN"

@dataclass
class Order:
    order_uuid: UUID
    intent_uuid: UUID
    client_order_id: str

    venue_order_id: Optional[str] = None
    venue_id: int
    account_id: int
    instrument_id: int

    side: OrderSide
    quantity: Decimal
    quantity_filled: Decimal = Decimal("0")
    price: Optional[Decimal] = None
    order_type: OrderType
    time_in_force: TimeInForce
    post_only: bool = False
    reduce_only: bool = False

    # Grouping (v0.2 addition)
    order_group_id: Optional[UUID] = None
    group_role: GroupRole = GroupRole.SINGLE

    # Environment (v0.2 addition)
    execution_environment: ExecutionEnvironment
    settlement_type: SettlementType

    status: OrderStatus = OrderStatus.SUBMITTING
    status_changed_at: datetime
    submitted_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    raw_submission_payload: Optional[dict] = None
    raw_response_payload: Optional[dict] = None
```

State machine same as v0.1; valid transitions enforced by `OrderStateMachine` class which raises `OrderStateError` on invalid transitions.

### Stable idempotent client_order_id (v0.2 fix)

The single most important change from v0.1. **No time component, period.**

```python
def make_client_order_id(
    strategy_short: str,
    intent_uuid: UUID,
    venue_id: int,
    account_id: int,
) -> str:
    """
    Deterministic from immutable intent data only. NO time component.

    Retries of the same intent -- minutes, hours, or days later -- produce
    the same client_order_id. Database UNIQUE constraint on
    (venue_id, client_order_id) plus venue's own idempotency check
    prevent duplicates.

    Format: <strategy_short:6>_<uuid_short:20>_<checksum:4>
    Example: mn_lsp_a3f9c1b2d4e5f6789a01_3fa9
    Total: 6 + 1 + 20 + 1 + 4 = 32 chars (fits Binance, OKX, Bybit limits)
    """
    strategy_norm = normalize_strategy_name(strategy_short)[:6]
    uuid_short = str(intent_uuid).replace("-", "")[:20]

    checksum_input = f"{strategy_short}:{intent_uuid}:{venue_id}:{account_id}"
    checksum = hashlib.sha256(checksum_input.encode()).hexdigest()[:4]

    cid = f"{strategy_norm}_{uuid_short}_{checksum}"
    assert len(cid) <= 32, f"client_order_id too long: {len(cid)}"
    return cid
```

The unique constraint at the database level (`UNIQUE (venue_id, client_order_id)` per ledger v0.3) is the architectural prevention of duplicate orders.

### PortfolioSnapshot with consistency guarantees (v0.2)

```python
@dataclass(frozen=True)
class PortfolioSnapshot:
    portfolio_id: int
    snapshot_id: UUID
    risk_version: int
    snapshot_at: datetime

    conservative_nav_usd: Decimal
    realized_pnl_today_usd: Decimal
    unrealized_pnl_usd: Decimal

    positions_by_instrument: dict[int, PositionInfo]

    gross_exposure_usd: Decimal
    net_exposure_usd: Decimal
    btc_beta: Decimal
    eth_beta: Decimal
    cluster_exposure_pct: dict[str, Decimal]

    margin_used_usd: Decimal
    margin_available_usd: Decimal

    drawdown_state: str
    drawdown_pct: Decimal
```

Each risk evaluation creates a fresh snapshot with a new snapshot_id. The snapshot is persisted; the RiskDecision references it.

## RiskKernel with advisory lock and skipped-check reporting (v0.2)

```python
class RiskKernel:
    """
    Single point through which every OrderIntent passes.

    v0.2 additions:
    - Advisory lock per portfolio_id during evaluate() prevents concurrent
      approvals from jointly breaching limits
    - Skipped checks (after fast-fail) are explicitly reported with
      result='skipped' and reason='prior_check_failed'
    - PortfolioSnapshot has snapshot_id and risk_version
    """

    def __init__(
        self,
        ledger: LedgerClient,
        kill_switch_manager: KillSwitchManager,
        policy_snapshot: PolicySnapshot,
        portfolio_snapshot_provider: PortfolioSnapshotProvider,
        venue_capabilities: VenueCapabilityRegistry,
    ):
        self.checks = [
            # Cheap checks first -- always run regardless of fast-fail
            SystemHealthCheck(),
            VenueAllowedCheck(venue_capabilities),
            StrategyPromotedCheck(ledger),
            KillSwitchClearCheck(kill_switch_manager),
            DrawdownStateCheck(policy_snapshot),

            # Medium checks
            DataFreshCheck(ledger),
            ReconciliationCheck(ledger),
            EdgeVsCostCheck(),
            FundingLimitCheck(policy_snapshot),
            MarginLimitCheck(policy_snapshot),
            StrategyConstraintsCheck(ledger, policy_snapshot),
            SelfCrossCheck(ledger),
            ConflictingOrderCheck(ledger),

            # Expensive checks last
            DailyVolumeLiquidityCheck(),
            OrderbookDepthCheck(),
            ExitLiquidityCheck(),
            StressExitCostCheck(),
            PositionLimitCheck(policy_snapshot),
            ClusterLimitCheck(policy_snapshot),
            NetExposureCheck(policy_snapshot),
            GrossExposureCheck(policy_snapshot),
            BetaLimitCheck(policy_snapshot),
        ]
        # 22 checks total in v0.2

        self.cheap_checks_count = 5
        self.ledger = ledger
        self.policy_snapshot = policy_snapshot
        self.portfolio_snapshot_provider = portfolio_snapshot_provider

    def evaluate(self, intent: OrderIntent) -> RiskDecision:
        with self.ledger.advisory_lock(
            f"risk_eval_portfolio_{intent.portfolio_id}"
        ):
            portfolio_snapshot = (
                self.portfolio_snapshot_provider.fresh_snapshot(
                    portfolio_id=intent.portfolio_id,
                )
            )
            check_results = []
            decision_value = "approved"
            failed_check = None
            fast_fail_triggered = False

            for idx, check in enumerate(self.checks):
                if (
                    fast_fail_triggered
                    and idx >= self.cheap_checks_count
                ):
                    check_results.append(RiskCheckResult(
                        check_name=check.name,
                        result="skipped",
                        skip_reason=(
                            f"prior_check_failed:{failed_check}"
                        ),
                    ))
                    continue

                start = time.monotonic()
                result = check.evaluate(
                    intent, portfolio_snapshot, self.policy_snapshot
                )
                result.elapsed_ms = (
                    (time.monotonic() - start) * 1000
                )
                check_results.append(result)

                if result.result == "fail":
                    decision_value = "rejected"
                    failed_check = result.check_name
                    fast_fail_triggered = True

            decision = RiskDecision(
                intent_uuid=intent.intent_uuid,
                decision=decision_value,
                failed_check=failed_check,
                check_results=check_results,
                decided_at=datetime.now(UTC),
                policy_snapshot_id=self.policy_snapshot.id,
                portfolio_snapshot_id=(
                    portfolio_snapshot.snapshot_id
                ),
                portfolio_risk_version=(
                    portfolio_snapshot.risk_version
                ),
            )

            self.ledger.persist_risk_decision(decision)

            if decision_value == "approved":
                self.ledger.reserve_exposure_for_intent(
                    intent=intent,
                    portfolio_snapshot=portfolio_snapshot,
                )

            return decision
```

The advisory lock + reservation pattern is the v0.2 fix for concurrent-approval breach.

## VenueAdapter Protocol (v0.2: I/O only, no ledger writes)

```python
class VenueAdapter(Protocol):
    """
    Pure venue I/O. Does NOT write to ledger.
    OMS and Reconciler own all ledger writes.
    """
    venue_id: int
    venue_code: str
    is_paper: bool
    capabilities: VenueCapabilities

    def submit(self, order: Order) -> AdapterResponse:
        """Submit order to venue. Does NOT update ledger."""
        ...

    def cancel(self, order: Order) -> AdapterResponse:
        """Cancel order at venue. Does NOT update ledger."""
        ...

    def fetch_order_by_client_id(
        self, account_id: int, client_order_id: str
    ) -> Optional[VenueOrder]:
        """Used by OMS for unknown-submit recovery."""
        ...

    def fetch_open_orders(
        self, account_id: int
    ) -> list[VenueOrder]:
        """Used by Reconciler."""
        ...

    def fetch_fills(
        self, account_id: int, since: datetime
    ) -> list[VenueFill]:
        ...

    def fetch_positions(
        self, account_id: int
    ) -> list[VenuePosition]:
        ...

    def fetch_balances(
        self, account_id: int
    ) -> list[VenueBalance]:
        ...

@dataclass
class AdapterResponse:
    success: bool
    venue_order_id: Optional[str] = None
    venue_fill_id: Optional[str] = None
    fill_quantity: Optional[Decimal] = None
    fill_price: Optional[Decimal] = None
    fill_liquidity: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    requires_recovery: bool = False
    raw_payload: dict = field(default_factory=dict)
```

### PaperAdapter (v0.2: deterministic via L2 snapshot ID)

```python
class PaperAdapter:
    """
    Simulates venue execution. Deterministic given:
    - Same OrderIntent
    - Same L2 snapshot ID
    - Same cost_model_hash
    - Same simulation_seed

    Does NOT write to ledger. Returns AdapterResponse with simulated
    fill data; OMS persists it as a fill row with environment=SHADOW,
    settlement_type=MODELED_FILL.
    """
    venue_code = "paper_<underlying_venue_code>"
    is_paper = True

    def __init__(
        self,
        venue_id: int,
        underlying_venue_code: str,
        cost_model: CostModel,
        l2_snapshot_store: L2SnapshotStore,
        capabilities: VenueCapabilities,
    ):
        self.venue_id = venue_id
        self.cost_model = cost_model
        self.l2_snapshot_store = l2_snapshot_store
        self.capabilities = capabilities

    def submit(self, order: Order) -> AdapterResponse:
        snapshot = self.l2_snapshot_store.fetch_addressable_snapshot(
            instrument_id=order.instrument_id,
            as_of=datetime.now(UTC),
        )

        sim_seed = stable_hash(
            f"{order.order_uuid}:{snapshot.snapshot_id}"
        )

        fill = self.cost_model.simulate_fill(
            order=order,
            l2_snapshot=snapshot,
            seed=sim_seed,
        )

        venue_order_id = f"PAPER_{order.order_uuid}"
        venue_fill_id = (
            f"PAPER_{order.order_uuid}_{fill.fill_idx}"
        )

        return AdapterResponse(
            success=True,
            venue_order_id=venue_order_id,
            venue_fill_id=venue_fill_id,
            fill_quantity=fill.quantity,
            fill_price=fill.price,
            fill_liquidity=fill.liquidity,
            raw_payload={
                "paper_fill": True,
                "l2_snapshot_id": str(snapshot.snapshot_id),
                "l2_snapshot_hash": snapshot.snapshot_hash,
                "cost_model_version": self.cost_model.version,
                "cost_model_hash": self.cost_model.hash,
                "simulation_seed": sim_seed,
            },
        )
```

### BinanceFuturesAdapter (v0.2: broader unknown-submit recovery)

```python
class BinanceFuturesAdapter:
    venue_code = "binance_futures"
    is_paper = False

    def __init__(self, venue_id, api_credentials, capabilities):
        self.venue_id = venue_id
        self.client = BinanceClient(api_credentials)
        self.capabilities = capabilities

    def submit(self, order: Order) -> AdapterResponse:
        if (
            order.post_only
            and not self.capabilities.supports_post_only
        ):
            return AdapterResponse(
                success=False,
                error_code="UNSUPPORTED_FEATURE",
                error_message="post_only not supported",
            )

        if (
            len(order.client_order_id)
            > self.capabilities.max_client_order_id_len
        ):
            return AdapterResponse(
                success=False,
                error_code="CLIENT_ORDER_ID_TOO_LONG",
                error_message=(
                    f"len {len(order.client_order_id)} > max "
                    f"{self.capabilities.max_client_order_id_len}"
                ),
            )

        payload = self._build_payload(order)

        try:
            response = self.client.futures_create_order(**payload)
            return AdapterResponse(
                success=True,
                venue_order_id=str(response["orderId"]),
                raw_payload={
                    "submission": payload,
                    "response": response,
                },
            )

        except BinanceAPIException as e:
            if self._is_potentially_successful_failure(e):
                return AdapterResponse(
                    success=False,
                    requires_recovery=True,
                    error_code=(
                        str(e.code) if hasattr(e, 'code')
                        else "UNKNOWN"
                    ),
                    error_message=str(e),
                    raw_payload={
                        "submission": payload,
                        "exception": str(e),
                    },
                )
            else:
                return AdapterResponse(
                    success=False,
                    error_code=(
                        str(e.code) if hasattr(e, 'code')
                        else "REJECTED"
                    ),
                    error_message=str(e),
                    raw_payload={
                        "submission": payload,
                        "exception": str(e),
                    },
                )

        except (NetworkError, TimeoutError) as e:
            return AdapterResponse(
                success=False,
                requires_recovery=True,
                error_code="NETWORK_TIMEOUT",
                error_message=str(e),
                raw_payload={
                    "submission": payload,
                    "exception": str(e),
                },
            )

    def _is_potentially_successful_failure(self, e) -> bool:
        """
        Returns True if the error might indicate the order DID reach
        the venue despite the error response.
        """
        return any([
            getattr(e, 'code', None) == -1014,  # duplicate order
            "duplicate" in str(e).lower(),
            getattr(e, 'code', None) == -1021,  # timestamp drift
            isinstance(e, (TimeoutError, ConnectionError)),
        ])

    def fetch_order_by_client_id(
        self, account_id, client_order_id
    ) -> Optional[VenueOrder]:
        try:
            order = self.client.futures_get_order(
                origClientOrderId=client_order_id,
            )
            return VenueOrder(...)
        except BinanceAPIException as e:
            if getattr(e, 'code', None) == -2013:
                return None
            raise
```

## OMS submission orchestration (v0.2)

```python
class OMS:
    """
    Orchestrates intent -> order -> submission.
    Owns all ledger writes for orders and fills.
    Adapters are pure I/O.
    """

    def __init__(
        self,
        risk_kernel: RiskKernel,
        adapter_registry: AdapterRegistry,
        ledger: LedgerClient,
        outbox: OmsOutbox,
        instrument_rules: InstrumentRuleEngine,
    ):
        self.risk_kernel = risk_kernel
        self.adapter_registry = adapter_registry
        self.ledger = ledger
        self.outbox = outbox
        self.instrument_rules = instrument_rules

    def submit_intent(self, intent: OrderIntent) -> SubmitResult:
        # 1. Persist intent to ledger
        self.ledger.persist_order_intent(intent)

        # 2. Risk kernel evaluation (advisory lock + reservation)
        risk_decision = self.risk_kernel.evaluate(intent)
        if risk_decision.decision == "rejected":
            return SubmitResult(
                approved=False,
                rejection_reason=(
                    f"Risk kernel rejected: "
                    f"{risk_decision.failed_check}"
                ),
                risk_decision=risk_decision,
            )

        # 3. Normalize to instrument rules (v0.2 addition)
        normalized = self.instrument_rules.normalize(intent)
        if not normalized.valid:
            self.ledger.release_exposure_reservation(
                intent.intent_uuid
            )
            return SubmitResult(
                approved=False,
                rejection_reason=(
                    f"Instrument rule violation: "
                    f"{normalized.violations}"
                ),
            )

        # 4. Create Order with stable client_order_id
        order = Order(
            order_uuid=gen_uuidv7(),
            intent_uuid=intent.intent_uuid,
            client_order_id=make_client_order_id(
                strategy_short=self.ledger.strategy_name(
                    intent.strategy_id
                ),
                intent_uuid=intent.intent_uuid,
                venue_id=intent.venue_id,
                account_id=intent.account_id,
            ),
            venue_id=intent.venue_id,
            account_id=intent.account_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=normalized.quantity,
            price=normalized.price,
            order_type=intent.order_type,
            time_in_force=intent.time_in_force,
            post_only=intent.post_only,
            reduce_only=intent.reduce_only,
            order_group_id=intent.order_group_id,
            group_role=intent.group_role,
            execution_environment=intent.execution_environment,
            settlement_type=intent.settlement_type,
            status=OrderStatus.SUBMITTING,
            status_changed_at=datetime.now(UTC),
        )

        # 5. Write-ahead: persist order BEFORE venue call
        self.ledger.persist_order(order)

        # 6. Submit to venue via adapter
        adapter = self.adapter_registry.get(intent.venue_id)
        response = adapter.submit(order)

        # 7. Handle response
        if response.success:
            order.venue_order_id = response.venue_order_id
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.now(UTC)
            order.raw_submission_payload = (
                response.raw_payload.get("submission")
            )
            order.raw_response_payload = response.raw_payload
            self.ledger.update_order(order)

            # If adapter returned immediate fill (paper adapter)
            if response.fill_quantity:
                self._record_fill(order, response)

            return SubmitResult(approved=True, order=order)

        elif response.requires_recovery:
            # v0.2: unknown-submit recovery
            order.status = OrderStatus.UNKNOWN
            self.ledger.update_order(order)
            self._recover_unknown_submit(order, adapter)
            return SubmitResult(
                approved=True,
                order=order,
                recovery_in_progress=True,
            )

        else:
            order.status = OrderStatus.REJECTED
            order.rejected_at = datetime.now(UTC)
            order.rejection_reason = response.error_message
            self.ledger.update_order(order)
            self.ledger.release_exposure_reservation(
                intent.intent_uuid
            )
            return SubmitResult(
                approved=False,
                rejection_reason=(
                    f"Venue rejected: {response.error_message}"
                ),
                order=order,
            )

    def _recover_unknown_submit(
        self, order: Order, adapter: VenueAdapter
    ):
        """
        v0.2: When submit response is ambiguous (timeout, network
        error, potentially-successful failure), look up order at
        venue by client_order_id.
        """
        venue_order = adapter.fetch_order_by_client_id(
            account_id=order.account_id,
            client_order_id=order.client_order_id,
        )

        if venue_order is not None:
            # Order exists at venue -- update local state
            order.venue_order_id = venue_order.venue_order_id
            order.status = self._map_venue_status(
                venue_order.status
            )
            order.submitted_at = venue_order.submitted_at
            self.ledger.update_order(order)
        else:
            # Order did NOT reach venue -- mark as rejected
            order.status = OrderStatus.REJECTED
            order.rejected_at = datetime.now(UTC)
            order.rejection_reason = "unknown_submit_not_found"
            self.ledger.update_order(order)
            self.ledger.release_exposure_reservation(
                order.intent_uuid
            )

    def _record_fill(
        self, order: Order, response: AdapterResponse
    ):
        """OMS owns fill writes. Adapter never writes to ledger."""
        fill = Fill(
            fill_uuid=gen_uuidv7(),
            order_uuid=order.order_uuid,
            venue_fill_id=response.venue_fill_id,
            venue_id=order.venue_id,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=response.fill_quantity,
            price=response.fill_price,
            liquidity=response.fill_liquidity,
            raw_fill_payload=response.raw_payload,
            filled_at=datetime.now(UTC),
        )
        self.ledger.persist_fill(fill)

        # Update order quantities
        order.quantity_filled += fill.quantity
        if order.quantity_filled >= order.quantity:
            order.status = OrderStatus.FILLED
            order.filled_at = fill.filled_at
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        self.ledger.update_order(order)

        # Create journal entry for the fill
        self.ledger.create_fill_journal(fill, order)
```

## Reconciler (v0.2: unknown venue orders, auto-action timeline)

```python
class Reconciler:
    """
    Continuous loop comparing ledger state to venue state.
    Runs every 30 seconds (configurable).
    """

    def __init__(
        self,
        ledger: LedgerClient,
        adapter_registry: AdapterRegistry,
        kill_switch_manager: KillSwitchManager,
        break_handler: BreakHandler,
    ):
        self.ledger = ledger
        self.adapter_registry = adapter_registry
        self.kill_switch = kill_switch_manager
        self.break_handler = break_handler

    def reconcile_cycle(self):
        for venue_id, adapter in self.adapter_registry.all():
            for account in self.ledger.active_accounts(venue_id):
                self._reconcile_orders(adapter, account)
                self._reconcile_fills(adapter, account)
                self._reconcile_positions(adapter, account)
                self._reconcile_balances(adapter, account)
                self._reconcile_funding(adapter, account)
                self._check_unknown_venue_orders(
                    adapter, account
                )

        self._check_unresolved_breaks()

    def _check_unknown_venue_orders(self, adapter, account):
        """
        v0.2 addition: detect venue orders not in our ledger.
        These indicate either:
        - A REPL/manual trade (P0 per incident_severity_policy)
        - A submission where ledger write succeeded but OMS crashed
          before updating status
        """
        venue_orders = adapter.fetch_open_orders(account.id)
        for vo in venue_orders:
            local = self.ledger.find_order_by_venue_id(
                venue_id=adapter.venue_id,
                venue_order_id=vo.venue_order_id,
            )
            if local is None:
                # Unknown order -- log break and alert
                self.break_handler.record_break(
                    break_type="unknown_venue_order",
                    venue_id=adapter.venue_id,
                    account_id=account.id,
                    local_state={"order": None},
                    venue_state={"order": vo.to_dict()},
                )

    def _check_unresolved_breaks(self):
        """
        Auto-trigger PORTFOLIO_HALT if any break is unresolved
        beyond 5 minutes per risk_policy v1.1 section 9.
        """
        old_breaks = self.ledger.find_unresolved_breaks(
            older_than_minutes=5
        )
        if old_breaks:
            self.kill_switch.engage(
                switch_type="PORTFOLIO_HALT",
                target="all",
                reason=(
                    f"{len(old_breaks)} reconciliation breaks "
                    f"unresolved >5min"
                ),
                auto_triggered=True,
            )
```

## Kill switch with action plans (v0.2 addition)

```python
class KillSwitchManager:
    def engage(
        self,
        switch_type: str,
        target: str,
        reason: str,
        operator_id: Optional[str] = None,
        operator_signature: Optional[str] = None,
        auto_triggered: bool = False,
        auto_trigger_source: Optional[str] = None,
    ):
        # Persist to risk.kill_switch_log
        self.ledger.persist_kill_switch_event(
            switch_type=switch_type,
            target=target,
            engaged=True,
            operator_id=operator_id or "SYSTEM",
            operator_signature=operator_signature,
            reason=reason,
            auto_triggered=auto_triggered,
            auto_trigger_source=auto_trigger_source,
            review_due_by=(
                datetime.now(UTC) + timedelta(hours=24)
                if auto_triggered else None
            ),
        )

        # Execute action plan (v0.2 addition)
        plan = self._build_action_plan(switch_type, target)
        plan.execute(self.ledger, self.adapter_registry)

    def _build_action_plan(
        self, switch_type: str, target: str
    ) -> ActionPlan:
        if switch_type == "STRATEGY_HALT":
            return StrategyHaltPlan(
                strategy_name=target,
                cancel_open_orders=True,
                reject_new_intents=True,
                manage_existing_positions=True,
            )
        elif switch_type == "VENUE_HALT":
            return VenueHaltPlan(
                venue_code=target,
                cancel_open_orders=True,
                reject_new_intents=True,
                attempt_flatten=True,
            )
        elif switch_type == "PORTFOLIO_HALT":
            return PortfolioHaltPlan(
                cancel_all_open_orders=True,
                reject_all_new_intents=True,
                alert_operator=True,
            )
```

## Acceptance criteria for Phase 1 implementation (v0.2)

The OMS is considered complete when ALL of the following pass:

1. **Write-ahead test:** order row exists in ledger BEFORE adapter.submit() is called; verified by injecting adapter failure and confirming order row present with status=SUBMITTING
2. **Idempotency test:** submitting the same intent twice produces only one order at the venue; second attempt hits UNIQUE constraint and returns existing order
3. **Risk kernel gate test:** intent with insufficient liquidity is rejected; no adapter call occurs
4. **Paper determinism test:** same intent + same L2 snapshot + same cost model produces byte-identical fill
5. **Unknown-submit recovery test:** adapter returns requires_recovery=True; OMS looks up by client_order_id and correctly reconciles
6. **Concurrent approval test:** two intents arriving simultaneously that would jointly breach a limit; advisory lock serializes them; second is rejected
7. **Kill switch test:** PORTFOLIO_HALT engaged; all subsequent intents rejected; existing orders cancelable
8. **Reconciler break detection test:** injected position discrepancy between ledger and venue produces reconciliation break within 60 seconds
9. **Auto-halt test:** reconciliation break unresolved for 5 minutes triggers automatic PORTFOLIO_HALT
10. **Decimal precision test:** no float type exists in any monetary field path from intent through fill to ledger entry; verified by AST scan of all OMS modules
11. **Promotion check test:** intent from un-promoted strategy is rejected at StrategyPromotedCheck; intent with wrong execution_environment vs promotion phase is rejected
12. **Instrument normalization test:** order with quantity violating lot_size is normalized before submission; order violating min_notional is rejected
13. **Self-cross test:** simultaneous buy and sell intents for same instrument from same strategy are detected and rejected
14. **Environment tagging test:** paper fills are tagged SHADOW/MODELED_FILL; live fills are tagged LIVE/LIVE_CONFIRMED; no cross-contamination
15. **Ledger ownership test:** adapter modules contain zero ledger write calls; only OMS and Reconciler write to ledger; verified by import-graph analysis

## Open design questions deferred to implementation

1. **Order rate limiting per venue.** Binance has rate limits per API key. The OMS should queue intents beyond the rate limit rather than submitting and getting rejected. Defer specific implementation to Phase 1 week 8 when Binance adapter is built.

2. **Multi-leg contingency execution.** The order_group_id and contingency_type fields exist; the contingency execution logic (e.g., cancel all legs if one leg fails for HEDGE_REQUIRED) is deferred to Phase 7+ when carry strategies need it.

3. **Partial fill handling for paper adapter.** Phase 1 paper adapter assumes full fills at modeled price. Partial fills (market impact causing only partial execution) deferred to Phase 2 when L2 simulation becomes more sophisticated.

4. **Warm-start reconciler after OMS restart.** On restart, the reconciler must first do a full reconciliation pass before the OMS accepts new intents. The implementation should enforce this ordering.

5. **Adapter health monitoring.** Beyond venue outage detection (which the reconciler does), proactive health checks (latency monitoring, error-rate tracking) are deferred to Phase 2.

## Revision log

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-05-02 | Wasseem Katt | Drafted but not committed due to three safety-critical bugs |
| 0.2 | 2026-05-02 | Wasseem Katt + external reviewer | Fixed client_order_id minute-boundary bug (no time component); switched all monetary types to Decimal; enforced adapter-is-IO-only / OMS-owns-ledger-writes; added deterministic L2 snapshot IDs for paper reproducibility; added advisory lock for concurrent-approval safety; added unknown-submit recovery flow; added execution_environment / settlement_type on OrderIntent; added order_group_id for multi-leg support; added exposure reservations; added DB-backed outbox queue; added kill-switch action plans; added venue capability registry; added instrument-rule normalization; added self-cross and conflicting-order checks; added unknown venue order auto-action in reconciler; added fast-fail skipped-check reporting; corrected "atomic" to "durable write-ahead" |

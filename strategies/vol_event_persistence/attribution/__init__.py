"""Attribution for vol_event_persistence.

Pure per-event P&L in basis points. Price-in, bps-out: no data fetching,
no clock. The runner supplies entry/exit prices and realised funding from
the kline + funding series; this layer only does the arithmetic.
"""

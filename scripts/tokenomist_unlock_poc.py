#!/usr/bin/env python3
"""
Tokenomist Unlock POC — drift-based mispricing, 1-year trial scope.
Built against the REAL v5 schema (docs.tokenomist.ai, confirmed).

NOT a Risk-Standard-v1 verdict: trial = 12mo backward, RS v1 needs >=24mo.
This answers: does the drift signal exist on ~1yr, i.e. is paying for Elite
(2yr backward) justified? Per token_unlock_drift_poc_spec.md (pre-registered).

Endpoints (base https://api.tokenomist.ai, auth header x-api-key):
  GET /v5/token/list                      -> {data:[{id,symbol,circulatingSupply,marketCap,...}]}
  GET /v5/unlock/events/{tokenId}?start&end&page&pageSize
       -> {metadata:{total,totalPages}, data:[{unlockDate, tokenSymbol,
            latestUpdateDate, cliffUnlocks:{cliffAmount,cliffValue,
            valueToMarketCap, allocationBreakdown:[{standardAllocationName,
            cliffAmount, referencePrice,...}]}}]}

KEY SCHEMA FACTS:
  - cliffUnlocks.valueToMarketCap = unlock value as % of market cap (PRECOMPUTED).
    Used as the >=5% threshold proxy. (True %-of-circulating-float can be derived
    from cliffAmount / circulatingSupply via Token List if you want exact; flagged.)
  - allocationBreakdown[].standardAllocationName = recipient type (Private
    Investors / founderTeam / community / publicInvestors / reserve / others).
  - latestUpdateDate = when the record was last revised. NOT a full revision
    history (Gate 2A: no as-of-date schedule archive), but flags revised events.
  - v5 Unlock Events = CLIFF unlocks only (matches POC spec: cliffs only).

Usage:
  export TOKENOMIST_KEY=...
  python3 tokenomist_unlock_poc.py --inspect                 # verify auth+schema, STOP
  python3 tokenomist_unlock_poc.py --inspect --token arbitrum
  python3 tokenomist_unlock_poc.py --count                   # >=5% event count + yearly dist
  python3 tokenomist_unlock_poc.py --count --pct 5 --out events.json
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.request, urllib.error, urllib.parse
from collections import defaultdict
from datetime import datetime, timezone

BASE = "https://api.tokenomist.ai"
KEY = os.environ.get("TOKENOMIST_KEY", "")
HDRS = {"x-api-key": KEY, "User-Agent": "hydra-poc/1", "Accept": "application/json"}

LOCKED_PCT = 5.0          # >=5% threshold (valueToMarketCap proxy). Do not tune to count.
WINDOW_START_YEAR = 2021


def _get(path, params=None, retries=3):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode("utf-8","ignore")[:200]
            except Exception: pass
            if e.code in (401, 403):
                print(f"  AUTH ERROR {e.code} on {path}: {body}", file=sys.stderr)
                return e.code, None
            if i == retries - 1:
                print(f"  HTTP {e.code} on {path}: {body}", file=sys.stderr)
                return e.code, None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if i == retries - 1:
                print(f"  fetch failed {path}: {e}", file=sys.stderr)
                return None, None
        time.sleep(1.5 * (i + 1))
    return None, None


def token_list(slugs=None):
    params = {"tokenId": ",".join(slugs)} if slugs else None
    status, body = _get("/v5/token/list", params)
    if status != 200 or not body:
        raise SystemExit(f"Token List failed (status {status}). Check key/endpoint.")
    return body.get("data", [])


def unlock_events(slug, start=None, end=None, page=1, page_size=200):
    return _get(f"/v5/unlock/events/{urllib.parse.quote(slug)}",
                {"start": start, "end": end, "page": page, "pageSize": page_size})


def inspect(token="arbitrum"):
    if not KEY:
        raise SystemExit("Set key first: export TOKENOMIST_KEY=...")
    print("=== AUTH + SCHEMA CHECK (x-api-key header) ===")
    status, body = _get("/v5/token/list")
    print(f"Token List -> HTTP {status}")
    if status != 200:
        print("Auth or endpoint problem. If 401/403, key not active or wrong header.")
        return
    data = body.get("data", [])
    print(f"tokens returned: {len(data)}  (trial cap = 50)")
    if data:
        t = data[0]
        print(f"sample token: id={t.get('id')!r} symbol={t.get('symbol')!r} "
              f"circSupply={t.get('circulatingSupply')} mcap={t.get('marketCap')}")
    # resolve requested token slug
    slug = token
    for t in data:
        if str(t.get("symbol","")).lower() == token.lower() or str(t.get("id","")).lower() == token.lower():
            slug = t.get("id"); break
    print(f"\n=== UNLOCK EVENTS for {slug!r} ===")
    status, ue = unlock_events(slug, page=1, page_size=5)
    print(f"HTTP {status}")
    if status == 200 and ue:
        md = ue.get("metadata", {})
        print(f"metadata: total={md.get('total')} totalPages={md.get('totalPages')} "
              f"pageSize={md.get('pageSize')}")
        evs = ue.get("data", [])
        print(f"events on page 1: {len(evs)}")
        if evs:
            ev = evs[0]
            cu = ev.get("cliffUnlocks", {}) or {}
            print(f"\nfirst event:")
            print(f"  unlockDate:       {ev.get('unlockDate')}")
            print(f"  latestUpdateDate: {ev.get('latestUpdateDate')}   <- Gate 2A: revision flag (no full history)")
            print(f"  dataSource:       {ev.get('dataSource')}")
            print(f"  cliffAmount:      {cu.get('cliffAmount')}")
            print(f"  cliffValue (USD): {cu.get('cliffValue')}")
            print(f"  valueToMarketCap: {cu.get('valueToMarketCap')}   <- the >=5% filter field (%)")
            ab = cu.get("allocationBreakdown", []) or []
            print(f"  allocations: {len(ab)}")
            if ab:
                print(f"    e.g. {ab[0].get('standardAllocationName')!r} "
                      f"amount={ab[0].get('cliffAmount')} refPrice={ab[0].get('referencePrice')}")
        print("\nSchema confirmed. Run --count for the >=5% event tally + yearly distribution.")
    else:
        print("Unlock Events call failed — paste this output.")


def count(pct=LOCKED_PCT, out=None):
    if not KEY:
        raise SystemExit("Set key first.")
    print(f"Counting cliff unlock events with valueToMarketCap >= {pct}% "
          f"({WINDOW_START_YEAR}-present, trial caps at 50 tokens / ~1yr back).")
    print("NOTE: not a §3 verdict (1yr < 24mo). Yearly dist = Section A clustering check.\n")
    toks = token_list()
    print(f"tokens available: {len(toks)}")
    by_year = defaultdict(int)
    by_year_recipient = defaultdict(lambda: defaultdict(int))
    qualifying = []
    revised = 0
    for i, t in enumerate(toks):
        slug = t.get("id")
        if not slug:
            continue
        page = 1
        while True:
            status, ue = unlock_events(slug, page=page, page_size=200)
            if status != 200 or not ue:
                break
            for ev in ue.get("data", []):
                cu = ev.get("cliffUnlocks", {}) or {}
                vmc = cu.get("valueToMarketCap")
                if vmc is None or vmc < pct:
                    continue
                ds = ev.get("unlockDate")
                if not ds:
                    continue
                try:
                    yr = datetime.fromisoformat(ds.replace("Z","+00:00")).year
                except Exception:
                    continue
                if yr < WINDOW_START_YEAR:
                    continue
                by_year[yr] += 1
                if ev.get("latestUpdateDate"):
                    revised += 1
                # dominant recipient for this event
                ab = cu.get("allocationBreakdown", []) or []
                if ab:
                    top = max(ab, key=lambda a: a.get("cliffAmount") or 0)
                    by_year_recipient[yr][top.get("standardAllocationName","?")] += 1
                qualifying.append({"slug": slug, "symbol": ev.get("tokenSymbol"),
                                   "date": ds, "valueToMarketCap": vmc,
                                   "cliffValue": cu.get("cliffValue")})
            md = ue.get("metadata", {})
            if page >= (md.get("totalPages") or 1):
                break
            page += 1
            time.sleep(0.1)
        if (i+1) % 10 == 0:
            print(f"  ...{i+1}/{len(toks)} tokens, {len(qualifying)} qualifying so far", file=sys.stderr)
        time.sleep(0.1)

    print(f"\n=== RESULT: {len(qualifying)} cliff events >= {pct}% of mcap, {WINDOW_START_YEAR}+ ===")
    print(f"(of which {revised} have a latestUpdateDate / were revised)\n")
    print("Yearly distribution (the Section A clustering check):")
    for yr in sorted(by_year):
        print(f"  {yr}: {by_year[yr]:4d}   recipients: {dict(by_year_recipient[yr])}")
    print("\nRead: events spread across years = clustering risk LOW. "
          "Bunched early w/ thin recent = Section A risk. Total too small = data-limited.")
    if out:
        with open(out, "w") as f:
            json.dump({"pct": pct, "total": len(qualifying),
                       "by_year": dict(by_year), "events": qualifying}, f, indent=2, default=str)
        print(f"\nwrote {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--token", default="arbitrum")
    ap.add_argument("--pct", type=float, default=LOCKED_PCT)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.inspect: inspect(a.token)
    elif a.count: count(a.pct, a.out)
    else: print("Use --inspect first, then --count. See header.")


if __name__ == "__main__":
    main()

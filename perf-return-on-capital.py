#!/usr/bin/env python3
"""
Return on a FLUCTUATING capital base. Read-only, writes nothing to Firestore.

Three measures, three different questions — see wiki/return-on-average-capital.md:
  1. return on average engaged capital  -> what the deployed capital earned
  2. TWR (chained daily)                -> stock-picking quality, ignores sizing
  3. trade-level IRR                    -> annual rate the money actually compounded at

Usage: python3 perf-return-on-capital.py [hk|us] [YYYY-MM-DD start] [YYYY-MM-DD end]

Period P&L is the BALANCE-SHEET DELTA (realizedPnL + unrealizedPnL between the two
bounds), never the sum of dailyPnL: sessions with no snapshot lose their dailyPnL
entirely, so any summed/chained measure under-reports. The TWR below chains dailyPnL and
is therefore a floor. See wiki/snapshot-record-gaps.md.

The delta has its own failure mode, which the orphan check below reports: a position that
leaves the book with no matching sale takes its P&L out of unrealizedPnL without booking
it into realizedPnL, so the delta reads the removal as a gain (on a loser) or a loss (on
a winner). US 2026-07-21 lost 8 positions that way, worth 1,205.30 USD.
"""
import os, sys, datetime as dt
from collections import defaultdict
import firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
MARKETS = {
    "hk": ("portfolios", "cNcZwUx3nQMV96TbB1kSkQ62u8U2", "HKD"),
    "us": ("us-portfolios", "JJDY5whY9vNmCcRsi8kafMHZbmD2", "USD"),
}
D = dt.date.fromisoformat


def load(market):
    collection, user_id, _ = MARKETS[market]
    firebase_admin.initialize_app(credentials.Certificate(CRED))
    db = firestore.client()
    d = db.collection(collection).document(user_id).get().to_dict()
    return (sorted(d["snapshots"], key=lambda s: s["date"]),
            d.get("closedTrades") or [], d.get("positions") or [])


def equity(s):
    """Cumulative gross P&L state. Gross of fees: closedTrades fees are tracked
    separately, and open positions carry no buyFees field at all."""
    return (s.get("realizedPnL") or 0) + (s.get("unrealizedPnL") or 0)


def avg_engaged(snaps):
    """Day-weighted mean of capitalEngaged: each snapshot holds until the next one,
    so weekends and snapshot gaps carry the last known capital."""
    num = den = 0.0
    for i, s in enumerate(snaps):
        w = (D(snaps[i + 1]["date"]) - D(s["date"])).days if i + 1 < len(snaps) else 1
        num += (s.get("capitalEngaged") or 0) * w
        den += w
    return num / den


def twr(snaps):
    """Chained daily return on prior-close market value. Floor, not exact: sessions
    with no snapshot contribute nothing, and a position opened intraday earns P&L
    that is not in the previous day's base."""
    r = 1.0
    for i in range(1, len(snaps)):
        base, dp = snaps[i - 1].get("portfolioValue") or 0, snaps[i].get("dailyPnL")
        if base and dp is not None:
            r *= 1 + dp / base
    return r - 1


def irr(closed, positions, end_date, end_value):
    """Money-weighted annual rate. Bisection on XNPV — no scipy.
    Approximate for positions built in tranches: entryPrice is the averaged cost and
    entryDate the first buy, so the whole outflow is booked at the first date."""
    fl = []
    for c in closed:
        fl.append((D(c["entryDate"]), -(c["entryPrice"] * c["quantity"] + (c.get("buyFees") or 0))))
        fl.append((D(c["exitDate"]), +(c["exitPrice"] * c["quantity"] - (c.get("sellFees") or 0))))
    for p in positions:
        fl.append((D(p["entryDate"]), -(p["entryPrice"] * p["quantity"])))
    fl.append((D(end_date), +end_value))
    fl.sort()
    t0 = fl[0][0]
    npv = lambda r: sum(cf / (1 + r) ** ((d - t0).days / 365) for d, cf in fl)
    lo, hi = -0.95, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if npv(mid) > 0 else (lo, mid)
    return (lo + hi) / 2, len(fl), fl[0][0]


def orphan_exits(snaps, closed):
    """Positions that left the book with no sale dated inside the interval between the two
    snapshots. Matching on the interval, not a +/-N day window: a window mis-fires whenever
    snapshots are missing (HK 0177/1585 sold 05-28, no snapshot until 06-03)."""
    out = []
    for i in range(1, len(snaps)):
        prev, cur = snaps[i - 1], snaps[i]
        after = {p["ticker"] for p in (cur.get("positionsAtClose") or [])}
        for p in (prev.get("positionsAtClose") or []):
            if p["ticker"] in after:
                continue
            if any(c["ticker"] == p["ticker"] and prev["date"] <= c["exitDate"] <= cur["date"]
                   for c in closed):
                continue
            out.append((cur["date"], p["ticker"],
                        (p.get("closingPrice", 0) - p.get("entryPrice", 0)) * p.get("quantity", 0)))
    return out


def main():
    args = [a for a in sys.argv[1:]]
    market = args.pop(0) if args and args[0] in MARKETS else "hk"
    ccy = MARKETS[market][2]
    snaps, closed, positions = load(market)
    if len(args) > 0:
        snaps = [s for s in snaps if s["date"] >= args[0]]
    if len(args) > 1:
        snaps = [s for s in snaps if s["date"] <= args[1]]
    if len(snaps) < 2:
        sys.exit("need at least 2 snapshots in the window")

    a, b = snaps[0], snaps[-1]
    days = (D(b["date"]) - D(a["date"])).days
    pnl = equity(b) - equity(a)
    fees = sum(c.get("totalFees", 0) or 0 for c in closed if a["date"] < c["exitDate"] <= b["date"])
    cap = avg_engaged(snaps)
    caps = [s.get("capitalEngaged") or 0 for s in snaps]
    summed = sum(s.get("dailyPnL") or 0 for s in snaps[1:])

    orphans = orphan_exits(snaps, closed)
    orphan_pnl = sum(o[2] for o in orphans)

    print(f"\n{market.upper()}  WINDOW  {a['date']} -> {b['date']}   {len(snaps)} sessions, {days} calendar days ({ccy})\n")
    print(f"  average engaged capital (day-weighted)  {cap:>13,.0f}")
    print(f"  range   {min(caps):,.0f} -> {max(caps):,.0f}   (x{max(caps)/min(caps):.2f})\n")
    print(f"  P&L, balance-sheet delta                {pnl:>+13,.0f}")
    print(f"  sum of dailyPnL (under-reports)         {summed:>+13,.0f}   gap {summed-pnl:+,.0f}")
    print(f"  fees on exits in window                 {-fees:>+13,.0f}")
    print(f"  P&L net                                 {pnl-fees:>+13,.0f}\n")

    if orphans:
        material = abs(orphan_pnl) / cap > 0.001 if cap else False
        print(f"  !! {len(orphans)} position(s) left the book with NO sale in the interval"
              f"   {orphan_pnl:+,.2f}   ({'MATERIAL' if material else 'immaterial, <0.1% of capital'})")
        for d, t, pl in orphans:
            print(f"       {d}  {t:<9} {pl:>+12,.2f}")
        if material:
            print(f"     corrected P&L {pnl + orphan_pnl:>+12,.0f}  =  {(pnl+orphan_pnl)/cap*100:+.2f} % of average capital")
            print(f"     the TWR below is unaffected — it only chains held legs\n")
        else:
            print()
    print(f"  1. on average engaged capital   gross {pnl/cap*100:>+7.2f} %    net {(pnl-fees)/cap*100:>+7.2f} %")
    print(f"     extrapolated to 365 days     gross {pnl/cap*365/days*100:>+7.2f} %    net {(pnl-fees)/cap*365/days*100:>+7.2f} %")
    print(f"  2. TWR (floor)                        {twr(snaps)*100:>+7.2f} %")
    r, n, start = irr(closed, positions, b["date"], b.get("portfolioValue") or 0)
    if orphans and abs(orphan_pnl) / cap > 0.001 if cap else False:
        # The flow list is built from closedTrades + positions[]. A position that vanished
        # from both contributes neither its buy nor its proceeds, so the IRR describes only
        # the surviving book — not the account. US: 8 gone, IRR reads +85%/yr on a book that
        # actually lost money. Refuse to present it as the account's return.
        print(f"  3. trade-level IRR                    UNUSABLE — {len(orphans)} position(s) are missing")
        print(f"     from both closedTrades and positions[], so neither their cost nor their")
        print(f"     proceeds is in the flow list. (It would print {r*100:+.2f} %/yr, describing")
        print(f"     only the {len(positions)} surviving lines.) Record the {len(orphans)} sales to fix it.\n")
    else:
        print(f"  3. trade-level IRR, fees in           {r*100:>+7.2f} %/yr   ({n} flows from {start})\n")

    print(f"  {'month':<9}{'sess':>5}{'avg capital':>14}{'P&L':>12}{'%':>9}{'fees':>9}{'net %':>9}")
    by_m = defaultdict(list)
    for s in snaps:
        by_m[s["date"][:7]].append(s)
    prev_eq, prev_d, run = equity(a), a["date"], 0.0
    for m in sorted(by_m):
        ms = by_m[m]
        ac = sum(s.get("capitalEngaged") or 0 for s in ms) / len(ms)
        p = equity(ms[-1]) - prev_eq
        f = sum(c.get("totalFees", 0) or 0 for c in closed if prev_d < c["exitDate"] <= ms[-1]["date"])
        run += p
        print(f"  {m:<9}{len(ms):>5}{ac:>14,.0f}{p:>+12,.0f}{p/ac*100:>+8.2f}%{f:>9,.0f}{(p-f)/ac*100:>+8.2f}%")
        prev_eq, prev_d = equity(ms[-1]), ms[-1]["date"]

    # monthly deltas telescope to the window delta, or a month boundary was dropped
    assert abs(run - pnl) < 0.01, f"monthly deltas {run:,.2f} != window delta {pnl:,.2f}"
    print(f"\n  check ok: monthly deltas sum to the window delta ({pnl:+,.0f})")


if __name__ == "__main__":
    main()

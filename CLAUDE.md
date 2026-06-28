# CLAUDE.md — HK Portfolio Firebase app

This project has a history of repeated data-loss incidents. Read this before doing anything.

## ⚠️ MANDATORY GATE — read the wiki procedures BEFORE any change

**Before editing code, patching Firestore, deploying rules, or running ANY script that writes to this app, Claude MUST first read every procedure page in the wiki.** This is not optional and applies even when the change "looks like a one-liner". A change that was not properly grounded in these procedures is how this portfolio keeps getting corrupted.

Wiki location: `../wiki/` (i.e. `TRADING/App portfolio /wiki/`).

Required reading, every time, in order:
1. [`wiki/index.md`](../wiki/index.md) — the gate + quick-reference rules
2. [`wiki/incidents.md`](../wiki/incidents.md) — what has gone wrong and why
3. [`wiki/reliability-risks.md`](../wiki/reliability-risks.md) — structural weaknesses (esp. #1, stale-tab overwrite)
4. [`wiki/recording-a-sale.md`](../wiki/recording-a-sale.md) — the invariant-safe edit procedure
5. [`wiki/dailypnl-formula.md`](../wiki/dailypnl-formula.md) — dailyPnL rules (prevClose = prior trading day; raw closes)
6. [`wiki/security-rules.md`](../wiki/security-rules.md) — the server-side safeguard

In the response, before the first write, Claude states which procedure pages were read.

## Hard rules for any data write

- **Dry-run → show Dany → confirm exact numbers/dates → `--apply` → independent verify.** Never auto-apply.
- **Add-to-stored, never full-rebuild** a snapshot (recompute pv/cap/unrealized/posCount from the affected legs only; keep the cron's values for untouched tickers).
- **Raw closes only** for any price math: `yfinance ... auto_adjust=False`. A ticker with a corporate action returns adjusted history by default, which does not match the stored raw settlement prices.
- **A data-integrity invariant that a stale/old-code client could violate belongs in Firestore Security Rules, not in client JS.** Client-side guards do not protect against the stale tab that causes the bug (it runs old code). See `wiki/security-rules.md`.
- **The cron + admin SDK bypass Security Rules.** Repair scripts and `update.py` are unaffected by the rules; only the browser is constrained.
- Every code change MUST be committed AND pushed in the same session (the repo is public; the cron and GitHub Pages serve `main`).

## After any change

Update the relevant wiki page(s) + `wiki/log.md` in the SAME session, and bump the page's `Last updated`. Ask: "which wiki page is now stale because of what I just did?"

---
name: verify
description: Verify a change to the HK/US Portfolio Tracker at its real surfaces (live GitHub Pages site, sync-folio-tickers.py, FinMC /api/folio). Read-only recipe.
---

# Verify (hk-portfolio-v2)

Surfaces, all read-only:

1. **Live site = HEAD?** (rule 10, deployed not working tree)
   ```bash
   gh api repos/Marcvrick/hk-portfolio-v2/pages/builds/latest --jq '.status+" "+.commit'
   curl -s "https://marcvrick.github.io/hk-portfolio-v2/index.html?cb=$RANDOM" -o $TMPDIR/live.html
   git show HEAD:index.html | cmp - $TMPDIR/live.html   # same for index-us.html
   ```
   The UI needs Firebase login: Claude cannot drive it. Check shipped code by grepping the live file.

2. **sync-folio-tickers.py**: `python3 sync-folio-tickers.py --dry-run` prints JSON and writes nothing.
   Without `--dry-run` it overwrites `portfolio-tickers.json`.
   Cross-check: Σ quantity × current_price must equal the last snapshot `value` (cron-settled pv).

3. **FinMC consumer**: backend on `127.0.0.1:8000`.
   `curl -s http://127.0.0.1:8000/api/folio` (HK) and `?market=US`. Each request re-runs
   sync-folio-tickers.py as a subprocess, so it exercises the working-tree script.

Gotchas: write Python checks to `$TMPDIR/*.py` (zsh `!` expansion). Never run `patch-*.py --apply`
during verification; those write to Firestore.

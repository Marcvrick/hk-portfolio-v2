# rules-test: exercising `firestore.rules` for real

```bash
cd rules-test
npm install
npm test          # needs Java (the Firestore emulator is a JVM process)
```

Reads `../firestore.rules` directly. There is no second copy of the ruleset anywhere,
deliberately: `deploy-firestore-rules.py` used to carry an inline copy that drifted
from the file it was meant to deploy.

## Why the emulator and not the API

`deploy-firestore-rules.py` posts to `firebaserules.googleapis.com/…:test`, and the
admin service account does not hold `firebaserules.rulesets.test`, a 403 that was
first recorded on 2026-06-28 and re-confirmed 2026-09-08. The project's rules test
has therefore never actually run against anything. The emulator needs no cloud
permissions, so this one does.

## What the matrix pins

The whole matrix runs twice, once per book (`portfolios` and `us-portfolios`), and
writes with `setDoc` rather than `updateDoc`, the app saves via a full-document
`set()` replace, which is the reason this bug class exists at all.

- **Everyday use keeps working**: add a position, full sale, partial sale, add a
  snapshot, an idle re-save, a multi-position sale.
- **A manual delete carries a receipt**: allowed with one, refused without, refused
  when deleting two behind a single receipt, and allowed as the very first delete on
  a book whose receipt log is still empty (so nothing needs seeding).
- **The 1138.HK bug** (2026-09-08): one position leaving the book with no sale and no
  receipt is refused. That is the exact shape of a stale tab reverting a fresh add,
  and the old ruleset allowed it unconditionally.
- **Old cached JS fails closed**: a client that omits `positionDeletions` is refused
  on *every* write, including one that only adds a position. This is the property no
  client-side guard could ever have, the offending tab runs old code, so it never
  loads the guard, but it cannot escape the server.
- **No regression** on the invariants that were already live: `closedTrades` and
  `snapshots` append-only, multi-position reverts refused.
- **Sharing untouched**: a friend in `allowedViewers` reads and cannot write; a
  stranger cannot read.

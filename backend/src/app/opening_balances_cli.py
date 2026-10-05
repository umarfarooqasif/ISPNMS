"""Load optional opening balances from a CSV (header: wasooli_id,amount[,note]).

    docker compose exec api python -m app.opening_balances_cli /data/storage/dues.csv            # preview
    docker compose exec api python -m app.opening_balances_cli /data/storage/dues.csv --commit   # load
"""

import argparse
import sys
from collections import Counter
from datetime import date

from app.core.db import session_factory
from app.services import audit
from app.services.billing import BillingError
from app.services.opening_balances import load_opening_balances, read_csv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path")
    ap.add_argument("--commit", action="store_true", help="write to the database (default: preview only)")
    ap.add_argument("--as-of", type=date.fromisoformat, help="date the balances are as of (YYYY-MM-DD, default today)")
    args = ap.parse_args(argv)

    try:
        rows = read_csv(args.csv_path)
    except (OSError, BillingError) as exc:
        print(f"error: {getattr(exc, 'message', exc)}", file=sys.stderr)
        return 2
    with session_factory()() as db:
        try:
            results = load_opening_balances(db, rows, as_of=args.as_of, dry_run=not args.commit)
        except BillingError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            return 2
        counts = Counter(r.status for r in results)
        for r in results:
            if r.status in ("INVALID", "NOT_FOUND", "ALREADY_EXISTS"):
                print(f"row {r.index + 2}: {r.status}: {r.message}")
        if args.commit:
            audit.log(db, user_id=None, action="opening_balances.load", entity="opening_balances",
                      entity_id=None, after={"counts": dict(counts), "source": "cli"}, request=None)
            db.commit()
        else:
            db.rollback()
    print(("COMMITTED " if args.commit else "PREVIEW (nothing written) ") + ", ".join(
        f"{k}={v}" for k, v in sorted(counts.items())))
    return 0 if not {"INVALID", "NOT_FOUND"} & set(counts) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Re-derive next due dates if the Wasooli "Recharge Date" turns out to be the LAST RECHARGE date.

The import copies the recharge date into each connection's next due date (RECHARGE_DATE_MEANS=NEXT_DUE).
If the dates in your export are really the day each customer last paid, run this ONCE, before the
first bill run, to move every due date one month forward (next due = last recharge + 1 month):

    docker compose exec api python -m app.rebase_due_dates_cli             # preview
    docker compose exec api python -m app.rebase_due_dates_cli --commit    # apply

Safe by design: only connections whose due date is still exactly the imported recharge date and that
have never been billed are touched. Billed connections and manually edited dates are left alone,
so running it twice changes nothing the second time.
"""

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.db import session_factory
from app.models import BillingRunItem, Connection
from app.services import audit
from app.services.billing_rules import add_months


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="write the change (default: preview only)")
    args = ap.parse_args(argv)

    with session_factory()() as db:
        billed = set(db.scalars(select(BillingRunItem.connection_id).where(
            BillingRunItem.connection_id.is_not(None),
            BillingRunItem.outcome.in_(("INVOICED", "FREE_SKIPPED", "CYCLES_SKIPPED")))))
        conns = list(db.scalars(select(Connection).where(
            Connection.deleted_at.is_(None), Connection.source_recharge_date.is_not(None),
            Connection.next_due_date == Connection.source_recharge_date)))
        counts: Counter = Counter()
        for c in conns:
            if c.id in billed:
                counts["left alone (already billed)"] += 1
                continue
            c.next_due_date = add_months(c.source_recharge_date, 1, c.billing_day)
            counts["moved forward one month"] += 1
        if args.commit and counts["moved forward one month"]:
            audit.log(db, user_id=None, action="connections.rebase_due_dates", entity="connection",
                      after={"counts": dict(counts), "source": "cli"}, request=None)
            db.commit()
        else:
            db.rollback()
    print(("COMMITTED: " if args.commit else "PREVIEW (nothing written): ")
          + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to do"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

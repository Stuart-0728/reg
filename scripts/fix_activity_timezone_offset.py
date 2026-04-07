#!/usr/bin/env python3
"""Repair historical activity datetime fields saved as Beijing naive instead of UTC naive.

Usage:
    python scripts/fix_activity_timezone_offset.py
    python scripts/fix_activity_timezone_offset.py --apply --yes --activity-ids 12,35,41
    python scripts/fix_activity_timezone_offset.py --apply --yes --all

This script shifts selected fields by -8 hours (Asia/Shanghai -> UTC) in DB for all rows
with non-null values. It is intended for one-time migration when old data was saved with
wrong timezone semantics.
"""

from __future__ import annotations

import argparse
from datetime import timedelta

from src import create_app, db
from src.models import Activity


FIELDS = (
    "start_time",
    "end_time",
    "registration_start_time",
    "registration_deadline",
)


def _parse_ids(raw: str) -> set[int]:
    result: set[int] = set()
    if not raw:
        return result
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        result.add(int(part))
    return result


def shift_activity_times(apply: bool, selected_ids: set[int] | None = None) -> tuple[int, int]:
    changed_rows = 0
    touched_fields = 0

    activities = Activity.query.all()
    for activity in activities:
        if selected_ids is not None and activity.id not in selected_ids:
            continue
        row_changed = False
        for field in FIELDS:
            value = getattr(activity, field, None)
            if value is None:
                continue
            setattr(activity, field, value - timedelta(hours=8))
            touched_fields += 1
            row_changed = True
        if row_changed:
            changed_rows += 1

    if apply:
        db.session.commit()
    else:
        db.session.rollback()

    return changed_rows, touched_fields


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix +8h offset in activity datetime fields")
    parser.add_argument("--apply", action="store_true", help="Apply migration changes")
    parser.add_argument("--yes", action="store_true", help="Confirm apply mode")
    parser.add_argument("--all", action="store_true", help="Apply to all activities (dangerous)")
    parser.add_argument("--activity-ids", default="", help="Comma-separated activity IDs to repair")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.apply and not args.yes:
            raise SystemExit("Refusing to apply without --yes")

        selected_ids = _parse_ids(args.activity_ids)
        if args.apply and not args.all and not selected_ids:
            raise SystemExit("For safety, apply mode requires --activity-ids or explicit --all")

        if args.apply and args.all:
            selected_ids = None

        changed_rows, touched_fields = shift_activity_times(apply=args.apply, selected_ids=selected_ids)
        mode = "APPLY" if args.apply else "DRY-RUN"
        scope_text = "all activities" if selected_ids is None else f"ids={sorted(selected_ids)}"
        print(f"[{mode}] scope: {scope_text}")
        print(f"[{mode}] affected activities: {changed_rows}, affected datetime fields: {touched_fields}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Backfill Density Script

Adds density_applied values to existing recipe_ingredients records
that used volume units during calculation.

Usage:
    python backfill_density.py --dry-run    # Preview changes
    python backfill_density.py              # Apply changes
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_connection
from recipe_manager import get_density, VOLUME_UNITS, UNIT_MAP


def backfill_density(dry_run=True):
    """Backfill density_applied for all ingredients using volume units."""
    print(f"\n{'='*60}")
    print(f"Density Backfill {'(DRY RUN)' if dry_run else '(LIVE)'}")
    print(f"{'='*60}\n")

    conn = get_connection()
    cur = conn.cursor()

    # Get all ingredients
    cur.execute('''
        SELECT id, item, unit, density_applied
        FROM recipe_ingredients
        WHERE unit IS NOT NULL AND item IS NOT NULL
    ''')
    ingredients = cur.fetchall()

    print(f"Found {len(ingredients)} ingredients to check\n")

    updates = []
    for ing_id, item, unit, current_density in ingredients:
        if not unit or not item:
            continue

        clean_unit = UNIT_MAP.get(unit.lower(), unit.lower())

        # Only process volume units
        if clean_unit not in VOLUME_UNITS:
            continue

        # Calculate what density should be
        correct_density = get_density(item)

        # Check if it needs updating
        if current_density != correct_density:
            updates.append({
                'id': ing_id,
                'item': item,
                'unit': unit,
                'old_density': current_density,
                'new_density': correct_density
            })

    print(f"Found {len(updates)} ingredients needing density update\n")

    # Show sample updates
    if updates:
        print("Sample updates:")
        for update in updates[:10]:
            old = update['old_density'] if update['old_density'] is not None else 'NULL'
            print(f"  - {update['item']} ({update['unit']}): {old} -> {update['new_density']}")
        if len(updates) > 10:
            print(f"  ... and {len(updates) - 10} more")

    # Apply updates
    if not dry_run and updates:
        print("\nApplying updates...")
        for update in updates:
            cur.execute('''
                UPDATE recipe_ingredients
                SET density_applied = %s
                WHERE id = %s
            ''', (update['new_density'], update['id']))

        conn.commit()
        print(f"Updated {len(updates)} records.")

    cur.close()
    conn.close()

    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"Total ingredients checked: {len(ingredients)}")
    print(f"Volume-based ingredients updated: {len(updates)}")

    if dry_run:
        print(f"\nThis was a DRY RUN. No changes were made.")
        print(f"Run without --dry-run to apply changes.")
    else:
        print(f"\nChanges have been applied to the database.")


def main():
    parser = argparse.ArgumentParser(
        description='Backfill density_applied values for existing ingredients'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without applying them'
    )

    args = parser.parse_args()
    backfill_density(dry_run=args.dry_run)


if __name__ == '__main__':
    main()

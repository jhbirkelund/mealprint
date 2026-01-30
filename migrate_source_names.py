#!/usr/bin/env python3
"""
Migration script to rename source_db values in climate_ingredients table.

Changes:
- 'danish' → 'ClimateDB'
- 'agribalyse' → 'Agribalyse'
- 'hestia' → 'Hestia'

Run: python migrate_source_names.py
Requires: DATABASE_URL environment variable
"""

import os
from db import get_connection

# Mapping of old values to new values
SOURCE_RENAMES = {
    'danish': 'ClimateDB',
    'agribalyse': 'Agribalyse',
    'hestia': 'Hestia',
}

def migrate():
    conn = get_connection()
    cur = conn.cursor()

    # Show current counts
    print("Current source_db distribution:")
    cur.execute("SELECT source_db, COUNT(*) FROM climate_ingredients GROUP BY source_db ORDER BY source_db")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]} ingredients")

    print("\nApplying renames...")

    # Apply each rename
    for old_name, new_name in SOURCE_RENAMES.items():
        cur.execute(
            "UPDATE climate_ingredients SET source_db = %s WHERE source_db = %s",
            (new_name, old_name)
        )
        count = cur.rowcount
        if count > 0:
            print(f"  Renamed '{old_name}' → '{new_name}' ({count} rows)")

    conn.commit()

    # Show new counts
    print("\nNew source_db distribution:")
    cur.execute("SELECT source_db, COUNT(*) FROM climate_ingredients GROUP BY source_db ORDER BY source_db")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]} ingredients")

    cur.close()
    conn.close()
    print("\nDone!")

if __name__ == '__main__':
    if not os.environ.get('DATABASE_URL'):
        print("Error: DATABASE_URL environment variable not set")
        exit(1)
    migrate()

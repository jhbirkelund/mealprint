"""
Recipe Verification Tool

Picks N random unverified published recipes, fetches their source URLs,
and prints a side-by-side comparison of stored vs. live ingredients
(names, amounts, and units) for manual review.

All checked recipes are marked 'under_review' in the DB. After reviewing
the output, Claude Code in the terminal updates statuses:
  - Matches → verified
  - Mismatches → left as under_review for fixing at /admin/verify

Usage:
    python verify_recipes.py              # check 10 recipes
    python verify_recipes.py --count 5   # check 5 recipes
"""

import argparse
from recipe_scrapers import scrape_me
from db import get_unverified_recipes, set_verification_status, get_connection
from psycopg2.extras import RealDictCursor


def get_stored_ingredients(recipe_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT original_line, item, amount, unit, grams
        FROM recipe_ingredients
        WHERE recipe_id = %s
        ORDER BY id
    ''', (recipe_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def format_stored(ing):
    amount = ing.get('amount') or ''
    unit = ing.get('unit') or ''
    item = ing.get('item') or '?'
    grams = ing.get('grams')

    amount_str = f"{amount:g}" if amount else ''
    unit_str = unit if unit and unit != 'g' else ''
    grams_str = f" ({grams:g}g)" if grams else ''

    parts = [p for p in [amount_str, unit_str, item] if p]
    return ' '.join(parts) + grams_str


def main():
    parser = argparse.ArgumentParser(description='Verify recipe ingredients against source URLs.')
    parser.add_argument('--count', type=int, default=10, help='Number of recipes to check (default: 10)')
    args = parser.parse_args()

    print(f"\nMealprint Recipe Verifier")
    print(f"{'='*70}")
    print(f"Fetching {args.count} random unverified recipes...\n")

    recipes = get_unverified_recipes(limit=args.count)

    if not recipes:
        print("No unverified recipes found. All caught up!")
        return

    fetch_errors = []

    for i, recipe in enumerate(recipes, 1):
        recipe_id = recipe['id']
        name = recipe['name']
        source = recipe.get('source', '')

        print(f"[{i}/{len(recipes)}] {name}")
        print(f"  ID:  {recipe_id}")
        print(f"  URL: {source}")

        stored = get_stored_ingredients(recipe_id)

        try:
            scraper = scrape_me(source)
            live = scraper.ingredients()
        except Exception as e:
            print(f"  ✗ Could not fetch source: {e}")
            print()
            set_verification_status(recipe_id, 'under_review')
            fetch_errors.append(recipe_id)
            continue

        # Side-by-side comparison
        col = 48
        print(f"\n  {'STORED (our DB)':<{col}} LIVE (source URL)")
        print(f"  {'-'*col} {'-'*col}")

        max_rows = max(len(stored), len(live))
        for j in range(max_rows):
            stored_str = format_stored(stored[j]) if j < len(stored) else '(missing)'
            live_str = live[j] if j < len(live) else '(missing)'
            print(f"  {stored_str:<{col}} {live_str}")

        print()

        # Mark as under_review — Claude Code will update to 'verified' for clean ones
        set_verification_status(recipe_id, 'under_review')

    print(f"{'='*70}")
    print(f"Checked {len(recipes)} recipes. All marked 'under_review'.")
    if fetch_errors:
        print(f"Could not fetch {len(fetch_errors)} source URL(s) — these need manual review.")
    print(f"\nNext: Claude Code reviews the output above and runs set_verification_status()")
    print(f"Flagged recipes available at /admin/verify\n")


if __name__ == '__main__':
    main()

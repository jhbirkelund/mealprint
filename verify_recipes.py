"""
Recipe Verification Tool

Two modes:

  python verify_recipes.py              # integrity check: compare stored vs live source (default)
  python verify_recipes.py --rematch    # rematch: re-run matching pipeline on stored original_lines
  python verify_recipes.py --count 5   # process 5 recipes

Integrity check (default):
    Fetches live source URLs and compares ingredient lines against what's stored.
    Flags added, removed, or changed lines. No DB writes.

Rematch:
    Re-runs the current matching pipeline on stored original_lines.
    Auto-corrects confident matches. No live fetching needed.
    New issues appended to ingredient_issues.md.
"""

import argparse
import os
from datetime import datetime, timezone
from bulk_scraper import scrape_url
from rapidfuzz import fuzz

from db import (
    init_db,
    get_unverified_recipes,
    get_under_review_recipes,
    set_verification_status,
    save_verification_notes,
    get_stored_ingredients_for_verification,
    update_ingredient_for_verification,
    update_recipe_totals_after_verification,
)
from ingredient_matcher import parse_ingredients, calculate_ingredient, load_climate_names

ISSUES_FILE = os.path.join(os.path.dirname(__file__), 'ingredient_issues.md')

# Issue thresholds
WEIGHT_HIGH_G = 1000   # flag single ingredient above this
WEIGHT_LOW_G  = 0.05   # flag single ingredient below this


def load_existing_issues():
    """Return raw text of ingredient_issues.md for duplicate-checking."""
    try:
        with open(ISSUES_FILE, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return ''


def append_issues_to_file(new_issues, recipe_name):
    """Append genuinely new issues to the Open section of ingredient_issues.md."""
    if not new_issues:
        return

    existing = load_existing_issues()
    added = []

    for issue in new_issues:
        key = issue['line'].lower().strip()
        if key in existing.lower():
            continue

        label = {
            'weight_too_high': 'Unit / Weight bugs',
            'weight_too_low':  'Unit / Weight bugs',
            'no_match':        'Ingredient match bugs',
            'low_confidence':  'Ingredient match bugs',
        }.get(issue['type'], 'Unit / Weight bugs')

        line = f"- **`{issue['line']}`** → {issue['detail']} *(Found: {recipe_name})*\n"
        added.append((label, line))

    if not added:
        return

    with open(ISSUES_FILE, 'r') as f:
        content = f.read()

    for label, line in added:
        heading = f'### {label}'
        if heading in content:
            insert_at = content.index(heading)
            block_end = content.find('\n\n', insert_at + len(heading))
            if block_end == -1:
                content += line
            else:
                content = content[:block_end] + '\n' + line.rstrip() + content[block_end:]
        else:
            new_block = f'\n{heading}\n\n{line}'
            content = content.replace('\n---\n\n## Fixed', new_block + '\n---\n\n## Fixed')

    with open(ISSUES_FILE, 'w') as f:
        f.write(content)

    print(f"  → {len(added)} new issue(s) added to ingredient_issues.md")


def detect_issues(line, grams, matched_item, confident):
    """Return issue dicts for a single ingredient (weight bugs and no-match only)."""
    issues = []
    if not matched_item:
        issues.append({
            'line': line,
            'type': 'no_match',
            'detail': 'No candidate found in climate DB',
        })
    if grams is not None:
        if grams > WEIGHT_HIGH_G:
            issues.append({
                'line': line,
                'type': 'weight_too_high',
                'detail': f'{grams:g}g seems too high — check unit/density',
            })
        elif 0 < grams < WEIGHT_LOW_G:
            issues.append({
                'line': line,
                'type': 'weight_too_low',
                'detail': f'{grams:g}g seems too low — check unit weight',
            })
    return issues


def find_best_stored_row(live_line, stored_rows, used_ids, threshold=40):
    """Find the stored row whose original_line best fuzzy-matches live_line.

    Uses WRatio so minor wording changes (e.g. '2-3' vs '2 – 3') still pair
    correctly. Each stored row can only be matched once (used_ids tracks taken rows).
    Returns None if best score is below threshold.
    """
    best_score = 0
    best_row = None
    live_lower = live_line.lower().strip()
    for row in stored_rows:
        if row['id'] in used_ids:
            continue
        stored_line = (row['original_line'] or '').lower().strip()
        score = fuzz.WRatio(live_lower, stored_line)
        if score > best_score:
            best_score = score
            best_row = row
    return best_row if best_score >= threshold else None


def check_integrity(recipe):
    """
    Fetch live source and compare ingredient lines against stored original_lines.
    Flags added, removed, or changed lines. Does NOT modify the DB.
    Returns (notes_dict, terminal_output_lines).
    """
    recipe_id = recipe['id']
    source = recipe.get('source', '')

    out = []
    out.append(f"  URL: {source}")

    stored = get_stored_ingredients_for_verification(recipe_id)

    try:
        scraper = scrape_url(source)
        live_lines = scraper.ingredients()
    except Exception as e:
        out.append(f"  ✗ Could not fetch source: {e}")
        notes = {
            'run_at':      datetime.now(timezone.utc).isoformat(),
            'mode':        'integrity',
            'fetch_error': str(e),
            'changes':     [],
            'issues':      [],
        }
        return notes, out

    out.append(f"  Live: {len(live_lines)} lines | Stored: {len(stored)} rows")

    used_stored_ids = set()
    added = []
    text_changed = []

    for live_line in live_lines:
        best_row = find_best_stored_row(live_line, stored, used_stored_ids, threshold=60)
        if best_row:
            used_stored_ids.add(best_row['id'])
            score = fuzz.WRatio(
                live_line.lower().strip(),
                (best_row['original_line'] or '').lower().strip()
            )
            if score < 90:
                text_changed.append({'live': live_line, 'stored': best_row['original_line']})
                out.append(
                    f"  ~ {live_line[:50]:<52}  changed"
                    f"  (was: {(best_row['original_line'] or '')[:40]})"
                )
        else:
            added.append(live_line)
            out.append(f"  + {live_line[:50]:<52}  new line not in stored")

    removed = []
    for row in stored:
        if row['id'] not in used_stored_ids:
            removed.append(row['original_line'] or '')
            out.append(f"  - {(row['original_line'] or '?')[:50]:<52}  removed from live source")

    if not added and not removed and not text_changed:
        out.append("  ✓ Live source matches stored — no changes detected")

    notes = {
        'run_at':       datetime.now(timezone.utc).isoformat(),
        'mode':         'integrity',
        'fetch_error':  None,
        'live_count':   len(live_lines),
        'stored_count': len(stored),
        'added':        added,
        'removed':      removed,
        'changed':      text_changed,
        'changes':      [],  # no auto-corrections in integrity mode
        'issues':       [],
    }
    return notes, out


def rematch_recipe(recipe, climate_names):
    """
    Re-run the matching pipeline on stored original_lines.
    Updates item/grams/co2 for confident matches. Does NOT fetch live source.
    Returns (notes_dict, terminal_output_lines, issues_list).
    """
    recipe_id = recipe['id']

    out = []

    stored = get_stored_ingredients_for_verification(recipe_id)
    out.append(f"  Re-matching {len(stored)} stored lines")

    changes = []
    all_issues = []
    any_updated = False

    for stored_row in stored:
        original_line = stored_row['original_line'] or ''
        if not original_line:
            continue

        parsed = parse_ingredients(original_line, climate_names)
        if not parsed:
            continue
        p = parsed[0]

        best_match = p['candidates'][0] if p['candidates'] else None
        confident = p['confident']

        calc = calculate_ingredient(p['amount'], p['unit'], best_match, original_line) if best_match else None

        grams_new = calc['grams'] if calc else None
        issues = detect_issues(original_line, grams_new, best_match, confident)
        all_issues.extend(issues)

        old_item  = stored_row['item']
        old_grams = float(stored_row['grams']) if stored_row['grams'] else None
        old_co2   = float(stored_row['co2'])   if stored_row['co2']   else None

        if confident and calc and calc['grams'] > 0:
            update_ingredient_for_verification(
                stored_row['id'],
                best_match,
                p['amount'],
                p['unit'],
                calc['grams'],
                calc['co2'],
                calc['source_db'],
                calc['density_applied'],
            )
            any_updated = True

            changed = (old_item != best_match) or (
                old_grams is not None and abs(old_grams - calc['grams']) > 0.5
            )
            if changed:
                changes.append({
                    'line':      original_line,
                    'old_item':  old_item,
                    'new_item':  best_match,
                    'old_grams': old_grams,
                    'new_grams': calc['grams'],
                    'old_co2':   old_co2,
                    'new_co2':   calc['co2'],
                })
                out.append(
                    f"  ✎ {original_line[:50]:<52}"
                    f"  {str(old_item or '?')[:25]} → {best_match[:25]}"
                    f"  ({old_grams or '?'}g → {calc['grams']:g}g)"
                )
        elif not confident and best_match:
            out.append(f"  ~ {original_line[:50]:<52}  low confidence — left unchanged")
        elif not best_match:
            out.append(f"  ? {original_line[:50]:<52}  no match found")

    if any_updated:
        update_recipe_totals_after_verification(recipe_id)

    if not changes and not all_issues:
        out.append("  ✓ No changes — already up to date")

    notes = {
        'run_at':       datetime.now(timezone.utc).isoformat(),
        'mode':         'rematch',
        'fetch_error':  None,
        'stored_count': len(stored),
        'changes':      changes,
        'issues':       [{'line': iss['line'], 'type': iss['type'], 'detail': iss['detail']}
                         for iss in all_issues],
    }
    return notes, out, all_issues


def main():
    parser = argparse.ArgumentParser(description='Verify and re-match recipe ingredients.')
    parser.add_argument('--count', type=int, default=10, help='Number of recipes to process (default: 10)')
    parser.add_argument('--rematch', action='store_true',
                        help='Re-run matching pipeline on stored original_lines (no live fetch)')
    args = parser.parse_args()

    init_db()

    if args.rematch:
        print(f"\nMealprint Recipe Re-matcher")
        print(f"{'='*70}")
        print(f"Re-running pipeline on {args.count} under-review recipes...\n")

        recipes = get_under_review_recipes(limit=args.count)
        if not recipes:
            print("No under-review recipes found. Run verify_recipes.py first to queue them.")
            return

        climate_names = load_climate_names()

        for i, recipe in enumerate(recipes, 1):
            name = recipe['name']
            print(f"[{i}/{len(recipes)}] {name}")

            notes, out, issues = rematch_recipe(recipe, climate_names)

            for line in out:
                print(line)

            save_verification_notes(recipe['id'], notes)
            append_issues_to_file(issues, name)
            print()

        print(f"{'='*70}")
        print(f"Done. {len(recipes)} recipes re-matched.")
        print(f"Review at /admin/verify\n")

    else:
        print(f"\nMealprint Recipe Verifier")
        print(f"{'='*70}")
        print(f"Checking {args.count} random unverified recipes against live source...\n")

        recipes = get_unverified_recipes(limit=args.count)
        if not recipes:
            print("No unverified recipes found. All caught up!")
            return

        fetch_errors = []

        for i, recipe in enumerate(recipes, 1):
            name = recipe['name']
            print(f"[{i}/{len(recipes)}] {name}")

            notes, out = check_integrity(recipe)

            for line in out:
                print(line)

            save_verification_notes(recipe['id'], notes)
            set_verification_status(recipe['id'], 'under_review')

            if notes.get('fetch_error'):
                fetch_errors.append(name)

            print()

        print(f"{'='*70}")
        print(f"Done. {len(recipes)} recipes marked 'under_review'.")
        if fetch_errors:
            print(f"Could not fetch: {', '.join(fetch_errors)}")
        print(f"Review at /admin/verify\n")


if __name__ == '__main__':
    main()

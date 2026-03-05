"""
Recipe Verification Tool

Picks N random unverified published recipes, fetches their source URLs,
re-parses ingredients with the current pipeline, auto-corrects any rows
where we have a confident match, stores a diff, and marks each recipe
as 'under_review' for sign-off at /admin/verify.

New issues found (suspect weights, no matches) are appended to ingredient_issues.md.

Usage:
    python verify_recipes.py              # check 10 recipes
    python verify_recipes.py --count 5   # check 5 recipes
"""

import argparse
import os
import re
from datetime import datetime, timezone
from recipe_scrapers import scrape_me

from db import (
    init_db,
    get_unverified_recipes,
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
        # Skip if this ingredient pattern is already mentioned in the file
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

    # Insert each new issue under the correct heading in the Open section
    with open(ISSUES_FILE, 'r') as f:
        content = f.read()

    for label, line in added:
        heading = f'### {label}'
        if heading in content:
            # Append after the heading block's last bullet
            insert_at = content.index(heading)
            # Find next blank line after heading + existing bullets
            block_end = content.find('\n\n', insert_at + len(heading))
            if block_end == -1:
                content += line
            else:
                content = content[:block_end] + '\n' + line.rstrip() + content[block_end:]
        else:
            # Create the heading before the Fixed section
            new_block = f'\n{heading}\n\n{line}'
            content = content.replace('\n---\n\n## Fixed', new_block + '\n---\n\n## Fixed')

    with open(ISSUES_FILE, 'w') as f:
        f.write(content)

    print(f"  → {len(added)} new issue(s) added to ingredient_issues.md")


def detect_issues(line, grams, matched_item, confident):
    """Return a list of issue dicts for a single ingredient.

    Only flags clear, fixable bugs: missing matches and suspect weights.
    Low-confidence matches are intentionally excluded — they're already
    visible in the terminal output and are often correct matches.
    """
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


def verify_recipe(recipe, climate_names):
    """
    Fetch live ingredient lines, re-parse, auto-correct stored rows,
    build a diff, and return (notes_dict, terminal_output_lines).
    """
    recipe_id = recipe['id']
    name = recipe['name']
    source = recipe.get('source', '')

    out = []
    out.append(f"  URL: {source}")

    stored = get_stored_ingredients_for_verification(recipe_id)

    # --- Fetch live ---
    try:
        scraper = scrape_me(source)
        live_lines = scraper.ingredients()
    except Exception as e:
        out.append(f"  ✗ Could not fetch source: {e}")
        notes = {
            'run_at': datetime.now(timezone.utc).isoformat(),
            'fetch_error': str(e),
            'changes': [],
            'issues': [],
        }
        return notes, out, []

    out.append(f"  Live: {len(live_lines)} lines | Stored: {len(stored)} rows")

    # --- Re-parse live lines ---
    raw = '\n'.join(live_lines)
    parsed = parse_ingredients(raw, climate_names)

    changes = []
    all_issues = []
    any_updated = False

    for i, p in enumerate(parsed):
        line = p['original_line']
        best_match = p['candidates'][0] if p['candidates'] else None
        confident = p['confident']

        calc = calculate_ingredient(p['amount'], p['unit'], best_match, line) if best_match else None

        # Detect issues on the freshly-parsed result
        grams_new = calc['grams'] if calc else None
        issues = detect_issues(line, grams_new, best_match, confident)
        all_issues.extend(issues)

        # Stored row at same position (may not exist if live has more lines)
        stored_row = stored[i] if i < len(stored) else None

        old_item  = stored_row['item']  if stored_row else None
        old_grams = float(stored_row['grams']) if stored_row and stored_row['grams'] else None
        old_co2   = float(stored_row['co2'])   if stored_row and stored_row['co2']   else None

        # Auto-correct: only if we have a confident match, a stored row, and a non-zero weight
        if confident and calc and stored_row and calc['grams'] > 0:
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
                    'line': line,
                    'old_item':  old_item,
                    'new_item':  best_match,
                    'old_grams': old_grams,
                    'new_grams': calc['grams'],
                    'old_co2':   old_co2,
                    'new_co2':   calc['co2'],
                })
                out.append(
                    f"  ✎ {line[:50]:<52}"
                    f"  {str(old_item or '?')[:25]} → {best_match[:25]}"
                    f"  ({old_grams or '?'}g → {calc['grams']:g}g)"
                )
        elif not confident and stored_row:
            out.append(f"  ~ {line[:50]:<52}  low confidence — left unchanged")
        elif not stored_row:
            out.append(f"  + {line[:50]:<52}  extra live line, no stored row to update")

    if any_updated:
        update_recipe_totals_after_verification(recipe_id)

    if not changes and not all_issues:
        out.append("  ✓ No changes — looks good")

    notes = {
        'run_at':       datetime.now(timezone.utc).isoformat(),
        'fetch_error':  None,
        'live_count':   len(live_lines),
        'stored_count': len(stored),
        'changes':      changes,
        'issues':       [{'line': iss['line'], 'type': iss['type'], 'detail': iss['detail']}
                         for iss in all_issues],
    }
    return notes, out, all_issues


def main():
    parser = argparse.ArgumentParser(description='Verify and auto-correct recipe ingredients.')
    parser.add_argument('--count', type=int, default=10, help='Number of recipes to check (default: 10)')
    args = parser.parse_args()

    init_db()  # apply any pending migrations (e.g. verification_notes column)

    print(f"\nMealprint Recipe Verifier")
    print(f"{'='*70}")
    print(f"Fetching {args.count} random unverified recipes...\n")

    recipes = get_unverified_recipes(limit=args.count)
    if not recipes:
        print("No unverified recipes found. All caught up!")
        return

    climate_names = load_climate_names()
    fetch_errors = []

    for i, recipe in enumerate(recipes, 1):
        name = recipe['name']
        print(f"[{i}/{len(recipes)}] {name}")

        notes, out, issues = verify_recipe(recipe, climate_names)

        for line in out:
            print(line)

        save_verification_notes(recipe['id'], notes)
        set_verification_status(recipe['id'], 'under_review')

        if notes.get('fetch_error'):
            fetch_errors.append(name)
        else:
            append_issues_to_file(issues, name)

        print()

    print(f"{'='*70}")
    print(f"Done. {len(recipes)} recipes marked 'under_review'.")
    if fetch_errors:
        print(f"Could not fetch: {', '.join(fetch_errors)}")
    print(f"Review at /admin/verify\n")


if __name__ == '__main__':
    main()

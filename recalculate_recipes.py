#!/usr/bin/env python3
"""
Recipe Recalculation Migration Script

Recalculates grams and CO2 for all existing recipes using the new
density-aware volume-to-weight conversion.

Usage:
    python recalculate_recipes.py --dry-run    # Preview changes
    python recalculate_recipes.py              # Apply changes

This script is needed because volume units (cup, tbsp, ml, etc.) now
use ingredient-specific densities instead of assuming water density (1g/ml).

Examples of corrections:
    - 1 cup flour: 240g -> 127g (density 0.53)
    - 1 cup honey: 240g -> 341g (density 1.42)
    - 1 cup oats: 240g -> 91g (density 0.38)
"""

import sys
import os
import argparse

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_connection, get_ingredient_by_name
from recipe_manager import get_weight_in_grams, calculate_rating, VOLUME_UNITS, UNIT_MAP


def get_all_recipes_with_ingredients(skip_verified=False):
    """Get all recipes with their ingredients for recalculation."""
    conn = get_connection()
    cur = conn.cursor()

    # Get all recipes, optionally skipping verified ones
    if skip_verified:
        cur.execute('''
            SELECT id, name, servings, total_co2, co2_per_serving
            FROM recipes
            WHERE verification_status IS DISTINCT FROM 'verified'
            ORDER BY created_at
        ''')
    else:
        cur.execute('''
            SELECT id, name, servings, total_co2, co2_per_serving
            FROM recipes
            ORDER BY created_at
        ''')
    recipes = cur.fetchall()

    result = []
    for recipe_row in recipes:
        recipe_id, name, servings, old_total_co2, old_co2_per_serving = recipe_row

        # Get ingredients for this recipe
        cur.execute('''
            SELECT id, item, amount, unit, grams, co2, source_db, matched_by, original_line
            FROM recipe_ingredients
            WHERE recipe_id = %s
        ''', (recipe_id,))
        ingredients = cur.fetchall()

        result.append({
            'id': recipe_id,
            'name': name,
            'servings': servings or 1,
            'old_total_co2': old_total_co2 or 0,
            'old_co2_per_serving': old_co2_per_serving or 0,
            'ingredients': [{
                'ing_id': ing[0],
                'item': ing[1],
                'amount': ing[2] or 0,
                'unit': ing[3] or 'g',
                'old_grams': ing[4] or 0,
                'old_co2': ing[5] or 0,
                'source_db': ing[6],
                'matched_by': ing[7],
                'original_line': ing[8]
            } for ing in ingredients]
        })

    cur.close()
    conn.close()
    return result


def recalculate_ingredient(item_name, amount, unit, original_line=None):
    """Recalculate grams and CO2 for a single ingredient using new density logic."""
    # Get CO2 value from database
    db_match = get_ingredient_by_name(item_name)
    if not db_match:
        return None, None

    co2_per_kg = db_match['co2_per_kg']

    # Calculate grams using new density-aware function.
    # Pass original_line as original_name so piece-weight lookup has the same
    # context as the initial parse (e.g. "1 bay leaf" matches "bay leaf": 0.5g).
    new_grams = get_weight_in_grams(amount, unit, item_name, original_name=original_line)
    new_co2 = (new_grams / 1000) * co2_per_kg

    return round(new_grams, 1), round(new_co2, 3)


def is_volume_unit(unit):
    """Check if unit is volume-based (affected by density changes)."""
    clean_unit = UNIT_MAP.get(unit.lower(), unit.lower())
    return clean_unit in VOLUME_UNITS


def run_migration(dry_run=True, skip_verified=False):
    """Run the recalculation migration."""
    print(f"\n{'='*60}")
    print(f"Recipe Recalculation Migration {'(DRY RUN)' if dry_run else '(LIVE)'}")
    if skip_verified:
        print(f"Skipping verified recipes")
    print(f"{'='*60}\n")

    recipes = get_all_recipes_with_ingredients(skip_verified=skip_verified)
    print(f"Found {len(recipes)} recipes to process\n")

    total_changes = 0
    recipes_changed = 0
    volume_ingredients_updated = 0

    for recipe in recipes:
        recipe_changed = False
        new_total_co2 = 0
        changes_log = []

        for ing in recipe['ingredients']:
            # Recalculate this ingredient
            new_grams, new_co2 = recalculate_ingredient(
                ing['item'], ing['amount'], ing['unit'], ing['original_line']
            )

            if new_grams is None:
                # Ingredient not found in DB, keep old values
                new_total_co2 += ing['old_co2']
                continue

            new_total_co2 += new_co2

            # Check if this is a meaningful change (more than 0.5g or 0.001 CO2)
            grams_diff = abs(new_grams - ing['old_grams'])
            co2_diff = abs(new_co2 - ing['old_co2'])

            if grams_diff > 0.5 or co2_diff > 0.001:
                recipe_changed = True
                total_changes += 1

                if is_volume_unit(ing['unit']):
                    volume_ingredients_updated += 1

                changes_log.append({
                    'item': ing['item'],
                    'amount': ing['amount'],
                    'unit': ing['unit'],
                    'old_grams': ing['old_grams'],
                    'new_grams': new_grams,
                    'old_co2': ing['old_co2'],
                    'new_co2': new_co2,
                    'ing_id': ing['ing_id'],
                    'is_volume': is_volume_unit(ing['unit'])
                })

        if recipe_changed:
            recipes_changed += 1
            new_total_co2 = round(new_total_co2, 3)
            new_co2_per_serving = round(new_total_co2 / recipe['servings'], 3)
            new_rating = calculate_rating(new_co2_per_serving)

            print(f"\n{'-'*50}")
            print(f"Recipe: {recipe['name']}")
            print(f"  Total CO2: {recipe['old_total_co2']:.3f} kg -> {new_total_co2:.3f} kg")
            print(f"  Per serving: {recipe['old_co2_per_serving']:.3f} kg -> {new_co2_per_serving:.3f} kg")

            for change in changes_log:
                volume_marker = " (volume)" if change['is_volume'] else ""
                print(f"    - {change['item']}: {change['amount']} {change['unit']}{volume_marker}")
                print(f"        Grams: {change['old_grams']:.1f} -> {change['new_grams']:.1f}")
                print(f"        CO2: {change['old_co2']:.3f} -> {change['new_co2']:.3f} kg")

            # Apply changes if not dry run
            if not dry_run:
                apply_recipe_changes(
                    recipe['id'],
                    changes_log,
                    new_total_co2,
                    new_co2_per_serving,
                    new_rating
                )
                print(f"  [UPDATED]")

    # Summary
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"Total recipes: {len(recipes)}")
    print(f"Recipes with changes: {recipes_changed}")
    print(f"Total ingredient changes: {total_changes}")
    print(f"Volume-based ingredients affected: {volume_ingredients_updated}")

    if dry_run:
        print(f"\nThis was a DRY RUN. No changes were made.")
        print(f"Run without --dry-run to apply changes.")
    else:
        print(f"\nChanges have been applied to the database.")


def apply_recipe_changes(recipe_id, changes_log, new_total_co2, new_co2_per_serving, new_rating):
    """Apply the calculated changes to the database."""
    conn = get_connection()
    cur = conn.cursor()

    # Update each changed ingredient
    for change in changes_log:
        cur.execute('''
            UPDATE recipe_ingredients
            SET grams = %s, co2 = %s
            WHERE id = %s
        ''', (change['new_grams'], change['new_co2'], change['ing_id']))

    # Update recipe totals
    cur.execute('''
        UPDATE recipes
        SET total_co2 = %s,
            co2_per_serving = %s,
            rating_label = %s,
            rating_color = %s,
            rating_emoji = %s
        WHERE id = %s
    ''', (
        new_total_co2,
        new_co2_per_serving,
        new_rating['label'],
        new_rating['color'],
        new_rating['emoji'],
        recipe_id
    ))

    conn.commit()
    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Recalculate recipe CO2 values with density-aware volume conversion'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without applying them'
    )
    parser.add_argument(
        '--skip-verified',
        action='store_true',
        help='Skip recipes with verification_status=verified'
    )

    args = parser.parse_args()
    run_migration(dry_run=args.dry_run, skip_verified=args.skip_verified)


if __name__ == '__main__':
    main()

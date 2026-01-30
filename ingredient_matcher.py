"""
Ingredient Matcher Module

Shared logic for parsing recipe ingredients and matching them to the climate database.
Used by both the web app (manual_app.py) and bulk scraper (bulk_scraper.py).
"""

import re
from quantulum3 import parser as quant_parser
from rapidfuzz import process, fuzz
from recipe_manager import UNIT_MAP, INGREDIENT_ALIASES, CONVERSIONS, get_weight_in_grams
from db import get_ingredient_by_name, get_all_climate_ingredients


# Informal units that quantulum3 doesn't recognize - map to standard units
# Note: Danish spoon units (tsk, spsk) are now in config/units.json unit_map
INFORMAL_UNITS = {
    # English
    'handful': '30g',
    'handfuls': '30g',
    'sprinkling': '2g',
    'sprinkle': '2g',
    # Danish
    'stk': '1 piece',    # styk (piece)
    'stk.': '1 piece',
    'knivspids': '0.5g', # knife tip
}


def load_climate_names():
    """Load climate ingredient names from database for fuzzy matching.

    Returns list of all searchable names (EN + DK + FR) to support
    multi-language recipe scraping and searching.
    """
    try:
        ingredients = get_all_climate_ingredients()
        names = []
        for ing in ingredients:
            # Add all language variants for searchability
            for name in [ing.get('name_en'), ing.get('name_dk'), ing.get('name_fr')]:
                if name and name not in names:
                    names.append(name)
        return names
    except Exception as e:
        print(f"Warning: Could not load climate ingredients: {e}")
        return []


def parse_ingredients(raw_text_block, climate_names=None):
    """
    Parse raw ingredient text and find matching candidates from climate database.

    Args:
        raw_text_block: Newline-separated ingredient strings (e.g., "200g beef\n2 onions")
        climate_names: Optional list of climate DB names (loaded from DB if not provided)

    Returns:
        List of dicts with keys: original_line, amount, unit, query, candidates, confident
    """
    if climate_names is None:
        climate_names = load_climate_names()

    processed_list = []
    lines = raw_text_block.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Preprocess: replace informal units with gram equivalents
        line_lower = line.lower()
        for informal, replacement in INFORMAL_UNITS.items():
            if informal in line_lower:
                line = re.sub(rf'(\d+\s*)?{informal}', replacement, line, flags=re.IGNORECASE)
                break

        quants = quant_parser.parse(line)
        if quants:
            amt = quants[0].value
            raw_unit_name = quants[0].unit.name.lower()
            unit = UNIT_MAP.get(raw_unit_name, raw_unit_name)
            search_query = str(line.replace(str(quants[0].surface), "").strip().split(',')[0])
        else:
            # No quantity found - default to 1 piece (e.g., "salt", "pepper to taste")
            amt = 1
            unit = 'piece'
            # Use the whole line as search query, clean up common phrases
            search_query = line
            for phrase in ['to taste', 'as needed', 'for garnish', 'optional', 'a pinch of', 'pinch of']:
                search_query = search_query.lower().replace(phrase, '').strip()
            search_query = search_query.strip(',')

        # Step 0: Check for alias matches (longest match first)
        search_lower = search_query.lower()
        for alias, replacement in sorted(INGREDIENT_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
            if alias in search_lower:
                search_query = replacement
                break

        # Step 1: Token-based contains matching
        search_words = [w.lower() for w in search_query.split() if len(w) > 3]

        def word_match_score(name):
            name_lower = name.lower()
            name_words = [w for w in name_lower.replace(',', '').split() if len(w) > 3]
            score = 0
            for sw in search_words:
                if sw in name_lower:
                    score += 2
            for nw in name_words:
                if nw in search_query.lower():
                    score += 2
            # Bonus: name starts with first search word
            if search_words and name_lower.startswith(search_words[0]):
                score += 5
            return score

        scored_matches = [(name, word_match_score(name)) for name in climate_names]
        contains_matches = [name for name, score in scored_matches if score > 0]
        contains_matches.sort(key=lambda n: (-word_match_score(n), len(n)))

        # Step 2: Always add fuzzy matches too
        fuzzy_matches = process.extract(
            search_query,
            climate_names,
            scorer=fuzz.WRatio,
            limit=20,
            score_cutoff=40
        )
        fuzzy_names = [match[0] for match in fuzzy_matches]

        # Combine: word matches first, then fuzzy (no duplicates), limit to 15
        candidate_names = contains_matches[:10] + [n for n in fuzzy_names if n not in contains_matches]
        candidate_names = candidate_names[:15]

        # Determine confidence: word match exists OR fuzzy score > 70
        best_fuzzy_score = fuzzy_matches[0][1] if fuzzy_matches else 0
        is_confident = len(contains_matches) > 0 or best_fuzzy_score >= 70

        processed_list.append({
            "original_line": line,
            "amount": amt,
            "unit": unit,
            "query": search_query,
            "candidates": candidate_names,
            "confident": is_confident
        })

    return processed_list


def calculate_ingredient(amount, unit, ingredient_name):
    """
    Calculate CO2 and nutrition for a single ingredient.

    Args:
        amount: Numeric amount (e.g., 200)
        unit: Unit string (e.g., 'g', 'cup', 'piece')
        ingredient_name: Matched ingredient name from climate DB

    Returns:
        Dict with keys: grams, co2, source_db, energy_kj, fat_g, carbs_g, protein_g
        Returns None if ingredient not found in database.
    """
    db_match = get_ingredient_by_name(ingredient_name)

    if not db_match:
        return None

    co2_val = db_match['co2_per_kg']
    energy_kj = db_match['energy_kj'] or 0
    fat = db_match['fat_g'] or 0
    carbs = db_match['carbs_g'] or 0
    protein = db_match['protein_g'] or 0
    source_db = db_match['source_db']

    grams = get_weight_in_grams(amount, unit, ingredient_name)
    item_co2 = (grams / 1000) * co2_val

    return {
        'grams': round(grams, 1),
        'co2': round(item_co2, 3),
        'source_db': source_db,
        'energy_kj': energy_kj,
        'fat_g': fat,
        'carbs_g': carbs,
        'protein_g': protein
    }


def calculate_recipe_totals(ingredients):
    """
    Calculate total CO2 and nutrition for a list of ingredients.

    Args:
        ingredients: List of dicts with keys: amount, unit, item (matched name), original_line

    Returns:
        Tuple of (total_co2, nutrition_dict, detailed_ingredients)
        nutrition_dict has keys: kcal, fat, carbs, protein (totals, not per serving)
    """
    total_co2 = 0
    total_kcal = 0
    total_fat = 0
    total_carbs = 0
    total_protein = 0
    detailed_ingredients = []

    for ing in ingredients:
        amount = float(ing['amount'])
        unit = ing['unit']
        match_name = ing['item']
        original_line = ing.get('original_line', '')

        result = calculate_ingredient(amount, unit, match_name)

        if not result:
            continue

        grams = result['grams']
        item_co2 = result['co2']
        total_co2 += item_co2

        # Nutrition (values are per 100g in database)
        if result['energy_kj']:
            total_kcal += (grams / 100) * (result['energy_kj'] / 4.184)
        if result['fat_g']:
            total_fat += (grams / 100) * result['fat_g']
        if result['carbs_g']:
            total_carbs += (grams / 100) * result['carbs_g']
        if result['protein_g']:
            total_protein += (grams / 100) * result['protein_g']

        detailed_ingredients.append({
            'original_line': original_line,
            'item': match_name,
            'amount': amount,
            'unit': unit,
            'grams': grams,
            'co2': item_co2,
            'source_db': result['source_db']
        })

    nutrition = {
        'kcal': round(total_kcal, 0),
        'fat': round(total_fat, 1),
        'carbs': round(total_carbs, 1),
        'protein': round(total_protein, 1)
    }

    return total_co2, nutrition, detailed_ingredients


def auto_match_ingredients(raw_text_block, climate_names=None):
    """
    Parse ingredients and auto-select the best match for each.
    Used by bulk scraper for automatic processing.

    Args:
        raw_text_block: Newline-separated ingredient strings
        climate_names: Optional list of climate DB names

    Returns:
        List of dicts with keys: original_line, amount, unit, item (best match), confident
    """
    parsed = parse_ingredients(raw_text_block, climate_names)

    matched = []
    for ing in parsed:
        if ing['candidates']:
            best_match = ing['candidates'][0]  # First candidate is best match
            matched.append({
                'original_line': ing['original_line'],
                'amount': ing['amount'],
                'unit': ing['unit'],
                'item': best_match,
                'confident': ing['confident']
            })

    return matched

from flask import Flask, request, render_template, redirect
import json
import os
from quantulum3 import parser
from recipe_manager import UNIT_MAP, INGREDIENT_ALIASES, CONVERSIONS, get_weight_in_grams, calculate_rating
from recipe_scrapers import scrape_me
from rapidfuzz import process, fuzz
from db import init_db, save_recipe_to_db, get_all_recipes, get_recipe_by_id, update_recipe_in_db, delete_recipe_from_db, get_ingredient_by_name, get_all_climate_ingredients
from admin import admin_bp

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Register admin blueprint
app.register_blueprint(admin_bp)

# Initialize database tables on startup
try:
    init_db()
    print("Database initialized successfully")
except Exception as e:
    print(f"Database initialization error: {e}")

# Load climate ingredients from Supabase at startup (cached for fuzzy matching)
# This unified table includes Danish DB (highest confidence) + Agribalyse (high confidence)
# We build two lookup structures:
#   CLIMATE_NAMES: list of all searchable names (EN + DK + FR) for fuzzy matching
#   CLIMATE_NAME_TO_DISPLAY: maps any language name to its display name (for dropdown selection)
try:
    CLIMATE_INGREDIENTS = get_all_climate_ingredients()

    # Build searchable names list (all languages) and mapping to display name
    CLIMATE_NAMES = []
    CLIMATE_NAME_TO_DISPLAY = {}  # lowercase name -> display name

    for ing in CLIMATE_INGREDIENTS:
        display_name = ing['name']  # Primary display name (EN or fallback)

        # Add all language variants to searchable names
        for name in [ing.get('name_en'), ing.get('name_dk'), ing.get('name_fr')]:
            if name and name not in CLIMATE_NAMES:
                CLIMATE_NAMES.append(name)
                CLIMATE_NAME_TO_DISPLAY[name.lower()] = display_name

    print(f"Loaded {len(CLIMATE_INGREDIENTS)} climate ingredients ({len(CLIMATE_NAMES)} searchable names)")
except Exception as e:
    print(f"Warning: Could not load climate ingredients: {e}")
    CLIMATE_INGREDIENTS = []
    CLIMATE_NAMES = []
    CLIMATE_NAME_TO_DISPLAY = {}


def get_processed_ingredients(raw_text_block):
    processed_list = []
    lines = raw_text_block.split('\n')

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

    for line in lines:
        line = line.strip()
        if not line: continue

        # Preprocess: replace informal units with gram equivalents
        line_lower = line.lower()
        for informal, replacement in INFORMAL_UNITS.items():
            if informal in line_lower:
                # Replace "1 handful" or "a handful" with "30g"
                import re
                line = re.sub(rf'(\d+\s*)?{informal}', replacement, line, flags=re.IGNORECASE)
                break

        quants = parser.parse(line)
        if quants:
            amt = quants[0].value
            raw_unit_name = quants[0].unit.name.lower()
            unit = UNIT_MAP.get(raw_unit_name, raw_unit_name)
            search_query = str(line.replace(str(quants[0].surface), "").strip().split(',')[0])

            # Step 0: Check for alias matches (longest match first)
            search_lower = search_query.lower()
            for alias, replacement in sorted(INGREDIENT_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
                if alias in search_lower:
                    search_query = replacement
                    break

            # Step 1: Token-based contains matching
            # Check if any word from search (>3 chars) appears in DB name, or vice versa
            # Uses cached CLIMATE_NAMES from Supabase (Danish + Agribalyse)
            search_words = [w.lower() for w in search_query.split() if len(w) > 3]

            def word_match_score(name):
                name_lower = name.lower()
                name_words = [w for w in name_lower.replace(',', '').split() if len(w) > 3]
                score = 0
                for sw in search_words:
                    if sw in name_lower:
                        score += 2  # Search word found in name
                for nw in name_words:
                    if nw in search_query.lower():
                        score += 2  # Name word found in search
                # Bonus: name starts with first search word (prefer "Pork, mince" over "Veal and pork, mince")
                if search_words and name_lower.startswith(search_words[0]):
                    score += 5
                return score

            scored_matches = [(name, word_match_score(name)) for name in CLIMATE_NAMES]
            contains_matches = [name for name, score in scored_matches if score > 0]
            # Sort by score descending, then by name length (prefer shorter names as tiebreaker)
            contains_matches.sort(key=lambda n: (-word_match_score(n), len(n)))

            # Step 2: Always add fuzzy matches too
            fuzzy_matches = process.extract(
                search_query,
                CLIMATE_NAMES,
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

@app.route('/')
def explore():
    """Home page - Explore recipes."""
    # Load recipes from database
    recipes = get_all_recipes()

    # Only show published recipes on the public explore page
    recipes = [r for r in recipes if r.get('is_published', True)]

    # Calculate rating for any recipes missing it
    for r in recipes:
        if not r.get('rating') or not r['rating'].get('label'):
            r['rating'] = calculate_rating(r.get('co2_per_serving', 0))

    # Collect all unique tags across recipes
    all_tags = set()
    for r in recipes:
        if r.get('tags'):
            all_tags.update(r['tags'])
    all_tags = sorted(all_tags)

    return render_template('history.html', recipes=recipes, all_tags=all_tags)

@app.route('/new')
def new_recipe():
    """Add new recipe page."""
    return render_template('home.html')

@app.route('/scrape', methods=['POST'])
def scrape():
    url = request.form.get('recipe_url')
    try:
        import re
        import urllib.request
        from html.parser import HTMLParser

        scraper = scrape_me(url)
        recipe_name = scraper.title() or ""
        servings = scraper.yields() or "1"
        # Extract just the number from yields (e.g., "4 servings" -> "4")
        servings_match = re.search(r'\d+', str(servings))
        servings = servings_match.group() if servings_match else "1"
        ingredients_list = scraper.ingredients()
        ingredients = "\n".join(ingredients_list)
        original_ingredients = "\n".join(ingredients_list)

        # Extract site rating from recipe_scrapers
        site_rating = ""
        try:
            ratings = scraper.ratings()
            if ratings:
                # ratings() returns a dict with 'rating' and 'count' keys
                if isinstance(ratings, dict):
                    rating_val = ratings.get('rating') or ratings.get('value')
                    if rating_val:
                        site_rating = str(rating_val)
                else:
                    site_rating = str(ratings)
        except:
            pass

        # Extract og:image from the page
        og_image_url = ""
        try:
            # Simple parser to extract og:image meta tag
            class OGImageParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.og_image = ""

                def handle_starttag(self, tag, attrs):
                    if tag == 'meta':
                        attrs_dict = dict(attrs)
                        if attrs_dict.get('property') == 'og:image' or attrs_dict.get('name') == 'og:image':
                            self.og_image = attrs_dict.get('content', '')

            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')
                parser = OGImageParser()
                parser.feed(html)
                og_image_url = parser.og_image
        except:
            pass

        return render_template('home.html',
            recipe_name=recipe_name,
            servings=servings,
            ingredients=ingredients,
            source=url,
            og_image_url=og_image_url,
            site_rating=site_rating,
            original_ingredients=original_ingredients
        )
    except Exception as e:
        return render_template('home.html', error=str(e))

@app.route('/summary', methods=['POST'])
def summary():
    recipe_name = request.form.get('recipe_name')
    servings = request.form.get('servings')
    raw_ingredients = request.form.get('ingredients')
    source = request.form.get('source', '')
    og_image_url = request.form.get('og_image_url', '')
    site_rating = request.form.get('site_rating', '')
    original_ingredients = request.form.get('original_ingredients', '')

    # If no original_ingredients provided (manual entry), use raw_ingredients
    if not original_ingredients:
        original_ingredients = raw_ingredients

    # Run the processing logic
    ingredients_with_matches = get_processed_ingredients(raw_ingredients)

    # Standardize units in the processed ingredients
    for item in ingredients_with_matches:
        raw_unit = item['unit'].lower().strip() if item['unit'] else ""
        item['unit'] = UNIT_MAP.get(raw_unit, raw_unit)

    # Get all ingredients from cached Supabase data (Danish + Agribalyse)
    # Build list with name and source for autocomplete display
    all_ingredients = []
    seen_names = set()
    for ing in CLIMATE_INGREDIENTS:
        source_db = ing.get('source', 'unknown')
        # Add all language variants with their source
        for name in [ing.get('name_en'), ing.get('name_dk'), ing.get('name_fr')]:
            if name and name not in seen_names:
                seen_names.add(name)
                all_ingredients.append({'name': name, 'source': source_db})
    all_ingredients.sort(key=lambda x: x['name'])
    available_units = list(CONVERSIONS['units'].keys())

    return render_template('summary.html',
        recipe_name=recipe_name,
        servings=servings,
        source=source,
        og_image_url=og_image_url,
        site_rating=site_rating,
        original_ingredients=original_ingredients,
        ingredients=ingredients_with_matches,
        all_ingredients=all_ingredients,
        units=available_units
    )

@app.route('/calculate', methods=['POST'])
def calculate():
    # Get lists of all submitted data
    recipe_name = request.form.get('recipe_name')
    source = request.form.get('source', '')
    og_image_url = request.form.get('og_image_url', '')
    site_rating = request.form.get('site_rating', '')
    original_ingredients = request.form.get('original_ingredients', '')
    amounts = request.form.getlist('amounts')
    units = request.form.getlist('units')
    selected_matches = request.form.getlist('selected_matches')
    original_lines = request.form.getlist('original_lines')

    total_co2 = 0
    total_kcal = 0
    total_fat = 0
    total_carbs = 0
    total_protein = 0
    detailed_ingredients = []

    # Loop through and calculate each item
    for i in range(len(selected_matches)):
        amt = float(amounts[i])
        unit = units[i]
        match_name = selected_matches[i]

        # Look up CO2 values from unified climate_ingredients table (Supabase)
        # Uses waterfall: Danish (highest) -> Agribalyse (high) -> HESTIA (medium)
        db_match = get_ingredient_by_name(match_name)

        if not db_match:
            # Skip if not found in database
            continue

        co2_val = db_match['co2_per_kg']
        energy_kj = db_match['energy_kj'] or 0
        fat = db_match['fat_g'] or 0
        carbs = db_match['carbs_g'] or 0
        protein = db_match['protein_g'] or 0
        source_db = db_match['source_db']

        # Calculate weight and impact
        grams = get_weight_in_grams(amt, unit, match_name)
        item_co2 = (grams / 1000) * co2_val
        total_co2 += item_co2

        # Calculate nutrition (values are per 100g)
        total_kcal += (grams / 100) * (energy_kj / 4.184) if energy_kj else 0
        total_fat += (grams / 100) * fat if fat else 0
        total_carbs += (grams / 100) * carbs if carbs else 0
        total_protein += (grams / 100) * protein if protein else 0

        detailed_ingredients.append({
            "original_line": original_lines[i] if i < len(original_lines) else '',
            "item": match_name,
            "amount": amt,
            "unit": unit,
            "grams": round(grams, 1),
            "co2": round(item_co2, 3),
            "source_db": source_db  # Track data source (danish/agribalyse/hestia/legacy)
        })

    # Get servings from the form and divide totals by servings
    servings = float(request.form.get('servings', 1))
    co2_per_serving = total_co2 / servings if servings > 0 else total_co2

    # Nutrition data for saving (per serving)
    nutrition = {
        "kcal": round(total_kcal / servings, 0) if servings > 0 else 0,
        "fat": round(total_fat / servings, 1) if servings > 0 else 0,
        "carbs": round(total_carbs / servings, 1) if servings > 0 else 0,
        "protein": round(total_protein / servings, 1) if servings > 0 else 0
    }

    # Calculate rating
    rating = calculate_rating(co2_per_serving)

    return render_template('calculate.html',
        recipe_name=recipe_name,
        servings=servings,
        total_co2=total_co2,
        co2_per_serving=co2_per_serving,
        rating=rating,
        nutrition=nutrition,
        ingredients=detailed_ingredients,
        source=source,
        og_image_url=og_image_url,
        site_rating=site_rating,
        original_ingredients=original_ingredients
    )

@app.route('/save/', methods=['POST'])
def save():
    recipe_name = request.form.get('recipe_name')
    servings = float(request.form.get('servings', 1))
    total_co2 = float(request.form.get('total_co2', 0))

    ingredients_json = request.form.get('detailed_ingredients')
    detailed_ingredients = json.loads(ingredients_json)

    nutrition_json = request.form.get('nutrition')
    nutrition = json.loads(nutrition_json) if nutrition_json else {}

    # Parse comma-separated tags into a list
    tags_raw = request.form.get('tags', '')
    tags = [tag.strip() for tag in tags_raw.split(',') if tag.strip()]

    # Get source, og_image_url, site_rating, and original ingredients
    source = request.form.get('source', '')
    og_image_url = request.form.get('og_image_url', '')
    site_rating = request.form.get('site_rating', '')
    original_ingredients = request.form.get('original_ingredients', '')

    # Calculate rating
    co2_per_serving = total_co2 / servings if servings > 0 else 0
    rating = calculate_rating(co2_per_serving)

    # Save to database
    recipe_id = save_recipe_to_db(recipe_name, detailed_ingredients, total_co2, servings, nutrition, tags, source, og_image_url, site_rating, original_ingredients, rating)

    # Redirect to the new recipe
    return redirect(f'/recipe/{recipe_id}')

# Legacy route - redirect to home
@app.route('/history')
def history():
    return redirect('/')

@app.route('/recipe/<recipe_id>')
def recipe(recipe_id):
    # Get recipe from database
    r = get_recipe_by_id(recipe_id)

    if not r:
        return redirect('/history')

    # Calculate rating if not stored
    if not r.get('rating') or not r['rating'].get('label'):
        r['rating'] = calculate_rating(r.get('co2_per_serving', 0))

    return render_template('recipe.html', recipe=r)

@app.route('/edit/<recipe_id>')
def edit(recipe_id):
    # Get recipe from database
    r = get_recipe_by_id(recipe_id)

    if not r:
        return render_template('home.html', error="Recipe not found")

    # Get all ingredients from cached Supabase data (Danish + Agribalyse)
    # Build list with name and source for autocomplete display
    all_ingredients = []
    seen_names = set()
    for ing in CLIMATE_INGREDIENTS:
        source_db = ing.get('source', 'unknown')
        for name in [ing.get('name_en'), ing.get('name_dk'), ing.get('name_fr')]:
            if name and name not in seen_names:
                seen_names.add(name)
                all_ingredients.append({'name': name, 'source': source_db})
    all_ingredients.sort(key=lambda x: x['name'])
    available_units = list(CONVERSIONS['units'].keys())

    # Check for publish flag (from admin review)
    publish = request.args.get('publish')

    return render_template('edit.html',
        recipe=r,
        all_ingredients=all_ingredients,
        units=available_units,
        publish=publish
    )

@app.route('/update/<recipe_id>', methods=['POST'])
def update(recipe_id):
    # Get form data
    recipe_name = request.form.get('recipe_name')
    servings = float(request.form.get('servings', 1))
    amounts = request.form.getlist('amounts')
    units = request.form.getlist('units')
    selected_matches = request.form.getlist('selected_matches')
    original_lines = request.form.getlist('original_lines')

    # Parse tags
    tags_raw = request.form.get('tags', '')
    tags = [tag.strip() for tag in tags_raw.split(',') if tag.strip()]

    # Get source, og_image_url, site_rating, and original ingredients
    source = request.form.get('source', '')
    og_image_url = request.form.get('og_image_url', '')
    site_rating = request.form.get('site_rating', '')
    original_ingredients = request.form.get('original_ingredients', '')

    # Recalculate CO2 and nutrition
    total_co2 = 0
    total_kcal = 0
    total_fat = 0
    total_carbs = 0
    total_protein = 0
    detailed_ingredients = []

    for i in range(len(selected_matches)):
        amt = float(amounts[i])
        unit = units[i]
        match_name = selected_matches[i]

        # Look up CO2 values from unified climate_ingredients table (Supabase)
        # Uses waterfall: Danish (highest) -> Agribalyse (high) -> HESTIA (medium)
        db_match = get_ingredient_by_name(match_name)

        if not db_match:
            # Skip if not found in database
            continue

        co2_val = db_match['co2_per_kg']
        energy_kj = db_match['energy_kj'] or 0
        fat = db_match['fat_g'] or 0
        carbs = db_match['carbs_g'] or 0
        protein = db_match['protein_g'] or 0
        source_db = db_match['source_db']

        grams = get_weight_in_grams(amt, unit, match_name)
        item_co2 = (grams / 1000) * co2_val
        total_co2 += item_co2

        # Nutrition
        total_kcal += (grams / 100) * (energy_kj / 4.184) if energy_kj else 0
        total_fat += (grams / 100) * fat if fat else 0
        total_carbs += (grams / 100) * carbs if carbs else 0
        total_protein += (grams / 100) * protein if protein else 0

        detailed_ingredients.append({
            "original_line": original_lines[i] if i < len(original_lines) else '',
            "item": match_name,
            "amount": float(amt),
            "unit": unit,
            "match": match_name,
            "grams": float(round(grams, 1)),
            "co2": float(round(item_co2, 3)),
            "source_db": source_db
        })

    # Calculate CO2 per serving and rating
    # Convert to Python float (pandas returns numpy types which PostgreSQL can't handle)
    total_co2 = float(total_co2)
    co2_per_serving = float(round(total_co2 / servings, 3)) if servings > 0 else 0.0
    rating = calculate_rating(co2_per_serving)

    # Nutrition per serving (all converted to Python float)
    nutrition = {
        "kcal": float(round(total_kcal / servings, 0)) if servings > 0 else 0.0,
        "fat": float(round(total_fat / servings, 1)) if servings > 0 else 0.0,
        "carbs": float(round(total_carbs / servings, 1)) if servings > 0 else 0.0,
        "protein": float(round(total_protein / servings, 1)) if servings > 0 else 0.0
    }

    # Update in database
    update_recipe_in_db(recipe_id, recipe_name, detailed_ingredients, total_co2, servings, nutrition, tags, source, og_image_url, site_rating, original_ingredients, rating)

    # If publish flag is set (from admin edit), publish the recipe
    publish = request.form.get('publish')
    if publish:
        from db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE recipes SET is_published = TRUE WHERE id = %s", (recipe_id,))
        conn.commit()
        cur.close()
        conn.close()

    # Redirect to the recipe page
    return redirect(f'/recipe/{recipe_id}')

@app.route('/delete/<recipe_id>')
def delete(recipe_id):
    # Delete from database
    delete_recipe_from_db(recipe_id)

    # Redirect to history
    return redirect('/history')

@app.route('/about-rating')
def about_rating():
    return render_template('about.html')

# This MUST be at the very bottom of the file
if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    app.run(debug=debug_mode, port=8080)
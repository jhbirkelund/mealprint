from flask import Flask, request
import pandas as pd
import html
import json
import os
from quantulum3 import parser
from recipe_manager import UNIT_MAP, INGREDIENT_ALIASES, CONVERSIONS, get_weight_in_grams, calculate_rating
from recipe_scrapers import scrape_me
from rapidfuzz import process, fuzz

app = Flask(__name__)

# Shared Material Design CSS
MATERIAL_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500&display=swap');
    @import url('https://fonts.googleapis.com/icon?family=Material+Icons');

    * { box-sizing: border-box; }

    body {
        font-family: 'Roboto', sans-serif;
        background: #f5f5f5;
        margin: 0;
        padding: 24px;
        padding-top: 72px;
        color: #212121;
    }

    .nav {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        background: #1976D2;
        padding: 0 24px;
        display: flex;
        align-items: center;
        height: 56px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        z-index: 1000;
    }

    .nav-brand {
        color: white;
        font-size: 20px;
        font-weight: 500;
        text-decoration: none;
        margin-right: 32px;
    }

    .nav-brand:hover { text-decoration: none; }

    .nav-links {
        display: flex;
        gap: 8px;
    }

    .nav-link {
        color: rgba(255,255,255,0.85);
        text-decoration: none;
        padding: 8px 16px;
        border-radius: 4px;
        font-size: 14px;
        font-weight: 500;
        transition: background 0.2s;
    }

    .nav-link:hover {
        background: rgba(255,255,255,0.1);
        text-decoration: none;
        color: white;
    }

    @media (max-width: 500px) {
        .nav { padding: 0 12px; }
        .nav-brand { font-size: 18px; margin-right: 16px; }
        .nav-link { padding: 8px 10px; font-size: 13px; }
    }

    .card {
        background: white;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        padding: 24px;
        max-width: 800px;
        margin: 0 auto 24px auto;
    }

    h1, h2 { font-weight: 400; color: #1976D2; margin-top: 0; }

    input[type="text"], input[type="number"], input[type="url"], textarea, select {
        width: 100%;
        padding: 12px;
        border: 1px solid #ddd;
        border-radius: 4px;
        font-size: 16px;
        font-family: 'Roboto', sans-serif;
        margin-top: 8px;
        transition: border-color 0.2s;
    }

    input:focus, textarea:focus, select:focus {
        outline: none;
        border-color: #1976D2;
    }

    label { font-weight: 500; color: #555; }

    .btn {
        background: #1976D2;
        color: white;
        border: none;
        padding: 12px 24px;
        border-radius: 4px;
        font-size: 14px;
        font-weight: 500;
        text-transform: uppercase;
        cursor: pointer;
        transition: background 0.2s, box-shadow 0.2s;
    }

    .btn:hover {
        background: #1565C0;
        box-shadow: 0 2px 8px rgba(25,118,210,0.3);
    }

    .btn-success { background: #43A047; }
    .btn-success:hover { background: #388E3C; }

    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; padding: 12px; background: #f5f5f5; border-bottom: 2px solid #ddd; font-weight: 500; }
    td { padding: 12px; border-bottom: 1px solid #eee; }

    a { color: #1976D2; text-decoration: none; }
    a:hover { text-decoration: underline; }

    .divider { border: none; border-top: 1px solid #eee; margin: 24px 0; }

    .chip {
        display: inline-block;
        background: #e3f2fd;
        color: #1976D2;
        padding: 6px 12px;
        border-radius: 16px;
        font-size: 13px;
        font-weight: 500;
        margin: 4px 4px 4px 0;
    }

    .chips { margin: 8px 0 16px 0; }
</style>
"""

NAV_BAR = """
<nav class="nav">
    <a href="/" class="nav-brand">Mealprint</a>
    <div class="nav-links">
        <a href="/" class="nav-link">New Recipe</a>
        <a href="/history" class="nav-link">History</a>
        <a href="/about-rating" class="nav-link">About</a>
    </div>
</nav>
"""

# Load the DB once at startup
df = pd.read_excel('climate_data.xlsx', sheet_name='DK')

def get_processed_ingredients(raw_text_block):
    processed_list = []
    lines = raw_text_block.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
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
            all_names = df['Name'].tolist()
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
                return score

            scored_matches = [(name, word_match_score(name)) for name in all_names]
            contains_matches = [name for name, score in scored_matches if score > 0]
            contains_matches.sort(key=lambda n: word_match_score(n), reverse=True)

            # Step 2: Always add fuzzy matches too
            fuzzy_matches = process.extract(
                search_query,
                all_names,
                scorer=fuzz.WRatio,
                limit=10,
                score_cutoff=50
            )
            fuzzy_names = [match[0] for match in fuzzy_matches]

            # Combine: word matches first, then fuzzy (no duplicates), limit to 10
            candidate_names = contains_matches[:5] + [n for n in fuzzy_names if n not in contains_matches]
            candidate_names = candidate_names[:10]

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
def home():
    return render_home()

def render_home(recipe_name="", servings="1", ingredients="", source="", notes="", original_ingredients=""):
    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card">
        <h1>Mealprint</h1>

        <form method="POST" action="/scrape">
            <label>Import from URL</label>
            <input type="url" name="recipe_url" placeholder="https://..." required>
            <br><br>
            <button type="submit" class="btn">Scrape Recipe</button>
        </form>

        <hr class="divider">

        <form method="POST" action="/summary">
            <label>Recipe Name</label>
            <input type="text" name="recipe_name" value="{html.escape(recipe_name)}" required>
            <br><br>
            <label>Servings</label>
            <input type="number" name="servings" value="{html.escape(str(servings))}" step="0.1" required>
            <br><br>
            <label>Ingredients (one per line)</label>
            <textarea name="ingredients" rows="10" placeholder="200g beef&#10;1 onion">{html.escape(ingredients)}</textarea>
            <br><br>
            <label>Source (optional)</label>
            <input type="text" name="source" value="{html.escape(source)}" placeholder="URL, cookbook name, or 'Family recipe'">
            <input type="hidden" name="notes" value="{html.escape(notes)}">
            <input type="hidden" name="original_ingredients" value="{html.escape(original_ingredients)}">
            <br><br>
            <button type="submit" class="btn btn-success">Process Ingredients</button>
        </form>

        <hr class="divider">
        <a href="/history">View saved recipes →</a>
    </div>
    """

@app.route('/scrape', methods=['POST'])
def scrape():
    url = request.form.get('recipe_url')
    try:
        scraper = scrape_me(url)
        recipe_name = scraper.title() or ""
        servings = scraper.yields() or "1"
        # Extract just the number from yields (e.g., "4 servings" -> "4")
        import re
        servings_match = re.search(r'\d+', str(servings))
        servings = servings_match.group() if servings_match else "1"
        ingredients_list = scraper.ingredients()
        ingredients = "\n".join(ingredients_list)
        original_ingredients = "\n".join(ingredients_list)
        instructions = scraper.instructions() or ""

        return render_home(recipe_name, servings, ingredients, source=url, notes=instructions, original_ingredients=original_ingredients)
    except Exception as e:
        return f"""
        {MATERIAL_CSS}
        {NAV_BAR}
        <div class="card">
            <h1>Scraping Failed</h1>
            <p>Error: {html.escape(str(e))}</p>
            <hr class="divider">
            <a href="/">← Go back</a>
        </div>
        """

@app.route('/summary', methods=['POST'])
def summary():
    name = request.form.get('recipe_name')
    servings = request.form.get('servings')
    raw_ingredients = request.form.get('ingredients')
    source = request.form.get('source', '')
    notes = request.form.get('notes', '')
    original_ingredients = request.form.get('original_ingredients', '')

    # If no original_ingredients provided (manual entry), use raw_ingredients
    if not original_ingredients:
        original_ingredients = raw_ingredients

    # Run the processing logic
    ingredients_with_matches = get_processed_ingredients(raw_ingredients)
    
    # Build datalist options once (all ingredients from DB)
    all_ingredients = sorted(df['Name'].unique().tolist())
    datalist_options = "".join([f'<option value="{name}">' for name in all_ingredients])

    # Build unit dropdown options
    available_units = list(CONVERSIONS['units'].keys())

    # Create the HTML rows (the "Correction UI")
    rows_html = ""
    for idx, item in enumerate(ingredients_with_matches):
        # Standardize units using UNIT_MAP
        raw_unit = item['unit'].lower().strip() if item['unit'] else""
        clean_unit = UNIT_MAP.get(raw_unit, raw_unit)

        # Use first match as default value, but only if confident
        has_matches = True if item['candidates'] else False
        is_confident = item.get('confident', False)
        default_value = item['candidates'][0] if (has_matches and is_confident) else ""

        # Style: red border if no confident match
        border_style = "" if is_confident else "border: 2px solid #e53935;"
        placeholder = "Type to search..." if is_confident else "No match - type to search"

        # Create dropdown with candidate matches
        datalist_id = f"ingredients_{idx}"
        input_id = f"input_{idx}"

        # Build select dropdown with candidates
        if item['candidates']:
            options_html = "".join([
                f'<option value="{cand}" {"selected" if cand == default_value else ""}>{cand}</option>'
                for cand in item['candidates']
            ])
            search_input = f'''<select name="selected_matches" id="{input_id}" style="width: 300px; {border_style}" required>
                {options_html}
            </select>
            <br><input type="text" list="{datalist_id}" placeholder="Or search all..." style="width: 300px; margin-top: 4px; font-size: 12px;" onchange="document.getElementById('{input_id}').insertAdjacentHTML('beforeend', '<option value=&quot;'+this.value+'&quot; selected>'+this.value+'</option>'); this.value='';">
            <datalist id="{datalist_id}">{datalist_options}</datalist>'''
        else:
            search_input = f'''<input type="text" id="{input_id}" name="selected_matches" list="{datalist_id}" value="" placeholder="{placeholder}" style="width: 300px; {border_style}" required>
            <datalist id="{datalist_id}">{datalist_options}</datalist>'''

        # Build unit dropdown with current unit selected
        unit_options = "".join([
            f'<option value="{u}" {"selected" if u == clean_unit else ""}>{u}</option>'
            for u in available_units
        ])

        rows_html += f"""
        <tr style="border-bottom: 1px solid #ddd;">
            <td style="padding: 15px; width: 35%">
                <div style="color: #888; font-size: 12px; margin-bottom: 8px;">{item['original_line']}</div>
                <input type="number" name="amounts" value="{item['amount']}" step="any" style="width: 80px; padding: 8px; margin-right: 8px;" required>
                <select name="units" style="width: 80px; padding: 8px;">
                    {unit_options}
                </select>
            </td>
            <td style="padding: 15px; width: 5%; text-align: center;">&rarr;</td>
            <td style="padding: 15px; width: 55%;">{search_input}</td>
            <td style="padding: 15px; width: 5%;">
                <button type="button" onclick="this.closest('tr').remove();" style="color: red; border: none; background: none; cursor: pointer; font-size: 20px;">&times;</button>
            </td>
        </tr>
        """

    # Build unit options for JavaScript
    unit_options_js = json.dumps(available_units)
    # Build ingredient options for JavaScript
    ingredients_js = json.dumps(all_ingredients)

    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card">
        <h2>Review & Correct</h2>
        <p><strong>{name}</strong> · {servings} servings</p>
        <form method="POST" action="/calculate">
            <input type="hidden" name="recipe_name" value="{name}">
            <input type="hidden" name="servings" value="{servings}">
            <input type="hidden" name="source" value="{html.escape(source)}">
            <input type="hidden" name="notes" value="{html.escape(notes)}">
            <input type="hidden" name="original_ingredients" value="{html.escape(original_ingredients)}">
            <table id="ingredients-table">
                {rows_html}
            </table>
            <button type="button" class="btn" onclick="addIngredientRow()" style="margin-top: 12px;">+ Add Ingredient</button>
            <br><br>
            <button type="submit" class="btn btn-success">Calculate Footprint</button>
        </form>
        <hr class="divider">
        <a href="/">← Start over</a>
    </div>

    <script>
    const availableUnits = {unit_options_js};
    const allIngredients = {ingredients_js};
    let rowCounter = 1000; // Start high to avoid ID conflicts

    function addIngredientRow() {{
        rowCounter++;
        const table = document.getElementById('ingredients-table');

        // Build unit options
        const unitOptions = availableUnits.map(u => `<option value="${{u}}">${{u}}</option>`).join('');

        // Build ingredient datalist
        const datalistId = `ingredients_${{rowCounter}}`;
        const datalistOptions = allIngredients.map(name => `<option value="${{name}}">`).join('');

        const row = document.createElement('tr');
        row.style.borderBottom = '1px solid #ddd';
        row.innerHTML = `
            <td style="padding: 15px; width: 35%">
                <div style="color: #888; font-size: 12px; margin-bottom: 8px;">(new ingredient)</div>
                <input type="number" name="amounts" value="100" step="any" style="width: 80px; padding: 8px; margin-right: 8px;" required>
                <select name="units" style="width: 80px; padding: 8px;">
                    ${{unitOptions}}
                </select>
            </td>
            <td style="padding: 15px; width: 5%; text-align: center;">&rarr;</td>
            <td style="padding: 15px; width: 55%;">
                <input type="text" name="selected_matches" list="${{datalistId}}" placeholder="Search ingredient..." style="width: 300px;" required>
                <datalist id="${{datalistId}}">${{datalistOptions}}</datalist>
            </td>
            <td style="padding: 15px; width: 5%;">
                <button type="button" onclick="this.closest('tr').remove();" style="color: red; border: none; background: none; cursor: pointer; font-size: 20px;">&times;</button>
            </td>
        `;

        table.appendChild(row);
    }}
    </script>
    """

@app.route('/calculate', methods=['POST'])
def calculate():
    # Get lists of all submitted data
    recipe_name = request.form.get('recipe_name')
    source = request.form.get('source', '')
    notes = request.form.get('notes', '')
    original_ingredients = request.form.get('original_ingredients', '')
    amounts = request.form.getlist('amounts')
    units = request.form.getlist('units')
    selected_matches = request.form.getlist('selected_matches')

    total_co2 = 0
    total_kcal = 0
    total_fat = 0
    total_carbs = 0
    total_protein = 0
    results_breakdown = []
    detailed_ingredients = []

    # Loop through and calculate each item
    for i in range(len(selected_matches)):
        amt = float(amounts[i])
        unit = units[i]
        match_name = selected_matches[i]

        # Look up CO2 values from loaded dataframe (df)
        db_row = df[df['Name'] == match_name].iloc[0]
        co2_val = db_row['Total kg CO2-eq/kg']

        # Calculate weight and impact
        grams = get_weight_in_grams(amt, unit, match_name)
        item_co2 = (grams / 1000) * co2_val
        total_co2 += item_co2

        # Calculate nutrition (values are per 100g)
        energy_kj = db_row['Energy (KJ/100 g)'] if pd.notna(db_row['Energy (KJ/100 g)']) else 0
        fat = db_row['Fat (g/100 g)'] if pd.notna(db_row['Fat (g/100 g)']) else 0
        carbs = db_row['Carbohydrate (g/100 g)'] if pd.notna(db_row['Carbohydrate (g/100 g)']) else 0
        protein = db_row['Protein (g/100 g)'] if pd.notna(db_row['Protein (g/100 g)']) else 0

        total_kcal += (grams / 100) * (energy_kj / 4.184)
        total_fat += (grams / 100) * fat
        total_carbs += (grams / 100) * carbs
        total_protein += (grams / 100) * protein

        results_breakdown.append(f"<tr><td>{match_name}</td><td>{grams:.0f} g</td><td>{item_co2:.2f} kg</td></tr>")

        # Build the dictionary for this specific ingredient
        detailed_ingredients.append({
            "item": match_name,
            "amount": amt,
            "unit": unit,
            "match": match_name,
            "grams": round(grams, 1),
            "co2": round(item_co2, 3)
        })

    # Get servings from the form and divide totals by servings
    servings_raw = request.form.get('servings', 1)
    servings = float(servings_raw)
    footprint_per_serving = total_co2 / servings if servings > 0 else total_co2
    kcal_per_serving = total_kcal / servings if servings > 0 else total_kcal
    fat_per_serving = total_fat / servings if servings > 0 else total_fat
    carbs_per_serving = total_carbs / servings if servings > 0 else total_carbs
    protein_per_serving = total_protein / servings if servings > 0 else total_protein

    # Nutrition data for saving
    nutrition = {
        "kcal": round(kcal_per_serving, 0),
        "fat": round(fat_per_serving, 1),
        "carbs": round(carbs_per_serving, 1),
        "protein": round(protein_per_serving, 1)
    }

    ingredients_json = html.escape(json.dumps(detailed_ingredients))
    nutrition_json = html.escape(json.dumps(nutrition))

    # Calculate rating for display
    rating = calculate_rating(footprint_per_serving)
    rating_badge = f'''<span style="display: inline-block; background: {rating['color']}; color: white; padding: 8px 16px; border-radius: 20px; font-weight: 500; font-size: 14px;">{rating['emoji']} {rating['label']} Footprint</span>'''

    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card">
        <h1>{recipe_name}</h1>
        <div style="margin: 16px 0;">
            {rating_badge}
            <span style="color: #666; font-size: 13px; margin-left: 12px;" title="Rating based on CO2 per serving. Compares to sustainable meal targets.">({footprint_per_serving:.2f} kg CO2 per serving) <a href="/about-rating" style="text-decoration: none; cursor: help; border-bottom: 1px dotted #999;">ⓘ</a></span>
        </div>
        <p><strong>Total footprint:</strong> {total_co2:.2f} kg CO2e · <strong>Servings:</strong> {servings:.0f}</p>

        <table>
            <tr>
                <th>Ingredient</th>
                <th>Weight</th>
                <th>CO2</th>
            </tr>
            {"".join(results_breakdown)}
        </table>

        <h2 style="margin-top: 32px;">Per Serving</h2>
        <table>
            <tr><td>CO2</td><td>{footprint_per_serving:.2f} kg</td></tr>
            <tr><td>Calories</td><td>{kcal_per_serving:.0f} kcal</td></tr>
            <tr><td>Fat</td><td>{fat_per_serving:.1f} g</td></tr>
            <tr><td>Carbs</td><td>{carbs_per_serving:.1f} g</td></tr>
            <tr><td>Protein</td><td>{protein_per_serving:.1f} g</td></tr>
        </table>

        <form method="POST" action="/save/">
            <input type="hidden" name="recipe_name" value="{recipe_name}">
            <input type="hidden" name="servings" value="{servings}">
            <input type="hidden" name="total_co2" value="{total_co2}">
            <input type="hidden" name="co2_per_serving" value="{footprint_per_serving}">
            <input type="hidden" name="nutrition" value="{nutrition_json}">
            <input type="hidden" name="detailed_ingredients" value="{ingredients_json}">
            <input type="hidden" name="original_ingredients" value="{html.escape(original_ingredients)}">
            {"".join([f'<input type="hidden" name="selected_matches" value="{m}">' for m in selected_matches])}

            <label>Source</label>
            <input type="text" name="source" value="{html.escape(source)}" placeholder="URL, cookbook, or 'Family recipe'">
            <br><br>
            <label>Tags (comma-separated)</label>
            <input type="text" name="tags" placeholder="dinner, quick, comfort-food">
            <br><br>
            <label>Notes / Instructions</label>
            <textarea name="notes" rows="8" style="font-size: 14px;">{html.escape(notes)}</textarea>
            <br><br>
            <button type="submit" class="btn">Save Recipe</button>
        </form>

        <hr class="divider">
        <a href="/">← Create another meal</a>
    </div>
    """

from recipe_manager import save_recipe
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

    # Get source, notes, and original ingredients
    source = request.form.get('source', '')
    notes = request.form.get('notes', '')
    original_ingredients = request.form.get('original_ingredients', '')

    save_recipe(recipe_name, detailed_ingredients, total_co2, servings, nutrition, tags, source, notes, original_ingredients)

    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card" style="text-align: center;">
        <h1>Saved!</h1>
        <p><strong>{recipe_name}</strong> has been added to your recipes.</p>
        <br>
        <a href="/" class="btn" style="display: inline-block; text-decoration: none;">Create Another Meal</a>
        <br><br>
        <a href="/history">View all recipes →</a>
    </div>
    """

# Show list of all recipes in DB:
@app.route('/history')
def history():
    import json
    import os

    #Check if the file exists first
    if not os.path.exists('recipes.json'):
        return f"""
        {MATERIAL_CSS}
        {NAV_BAR}
        <div class="card">
            <h1>No recipes yet</h1>
            <p>You haven't saved any recipes.</p>
            <br>
            <a href="/" class="btn" style="display: inline-block; text-decoration: none;">Create Your First Recipe</a>
        </div>
        """
    
    # Load recipes
    with open('recipes.json', 'r') as f:
        recipes = json.load(f)
    
    # Build table rows
    table_rows = ""
    for r in recipes:
        co2_per_serving = r.get('co2_per_serving', 0)
        # Get or calculate rating
        stored_rating = r.get('rating')
        if stored_rating:
            rating = stored_rating
        else:
            rating = calculate_rating(co2_per_serving)
        rating_badge = f'''<span style="display: inline-block; background: {rating['color']}; color: white; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 500;">{rating['emoji']} {rating['label']}</span>'''
        table_rows += f"<tr style='cursor: pointer;' onclick=\"window.location='/recipe/{r['id']}'\"><td>{r['name']}</td><td>{rating_badge}</td><td>{co2_per_serving:.2f} kg</td></tr>"

    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card">
        <h1>All Recipes</h1>
        <table>
            <tr>
                <th>Recipe</th>
                <th>Rating</th>
                <th>CO2 per serving</th>
            </tr>
            {table_rows}
        </table>
        <hr class="divider">
        <a href="/">← Create another recipe</a>
    </div>
    """

@app.route('/recipe/<recipe_id>')
def recipe(recipe_id):
    import os

    if not os.path.exists('recipes.json'):
        return f"""
        {MATERIAL_CSS}
        {NAV_BAR}
        <div class="card">
            <h1>Recipe not found</h1>
            <a href="/history">← Back to all recipes</a>
        </div>
        """

    with open('recipes.json', 'r') as f:
        recipes = json.load(f)

    # Find recipe by UUID
    r = next((recipe for recipe in recipes if recipe.get('id') == recipe_id), None)
    if not r:
        return f"""
        {MATERIAL_CSS}
        {NAV_BAR}
        <div class="card">
            <h1>Recipe not found</h1>
            <a href="/history">← Back to all recipes</a>
        </div>
        """

    # Build ingredients table
    ingredients_rows = ""
    for ing in r.get('ingredients', []):
        ingredients_rows += f"<tr><td>{ing.get('item', '')}</td><td>{ing.get('grams', 0):.0f} g</td><td>{ing.get('co2', 0):.2f} kg</td></tr>"

    # Get nutrition
    nutrition = r.get('metadata', {}).get('nutrition', {})
    kcal = nutrition.get('kcal', 0)
    fat = nutrition.get('fat', 0)
    carbs = nutrition.get('carbs', 0)
    protein = nutrition.get('protein', 0)

    # Build rating badge (calculate if not stored)
    stored_rating = r.get('rating')
    if stored_rating:
        rating = stored_rating
    else:
        rating = calculate_rating(r.get('co2_per_serving', 0))
    co2_kg = r.get('co2_per_serving', 0)
    rating_badge = f'''<span style="display: inline-block; background: {rating['color']}; color: white; padding: 8px 16px; border-radius: 20px; font-weight: 500; font-size: 14px;">{rating['emoji']} {rating['label']} Footprint</span>'''
    rating_section = f'''<div style="margin: 16px 0;">
        {rating_badge}
        <span style="color: #666; font-size: 13px; margin-left: 12px;" title="Rating based on CO2 per serving. Compares to sustainable meal targets.">({co2_kg:.2f} kg CO2 per serving) <a href="/about-rating" style="text-decoration: none; cursor: help; border-bottom: 1px dotted #999;">ⓘ</a></span>
    </div>'''

    # Build tags HTML
    tags = r.get('tags', [])
    tags_html = "".join([f'<span class="chip">{tag}</span>' for tag in tags])
    tags_section = f'<div class="chips">{tags_html}</div>' if tags else ""

    # Build source HTML (clickable if URL)
    source = r.get('source', '')
    if source.startswith('http'):
        source_html = f'<p style="color: #666; font-size: 14px;">Source: <a href="{source}" target="_blank">{source}</a></p>'
    elif source:
        source_html = f'<p style="color: #666; font-size: 14px;">Source: {source}</p>'
    else:
        source_html = ""

    # Build original ingredients section
    original_ing = r.get('original_ingredients', '')
    original_ing_html = f'<h2 style="margin-top: 24px;">Ingredients</h2><div style="white-space: pre-wrap; font-size: 14px;">{html.escape(original_ing)}</div>' if original_ing else ""

    # Build notes section
    notes_html = f'<h2 style="margin-top: 32px;">Instructions</h2><div style="white-space: pre-wrap; font-size: 14px;">{html.escape(r.get("notes", ""))}</div>' if r.get('notes') else ""

    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h1 style="margin: 0;">{r['name']}</h1>
            <div>
                <a href="/edit/{recipe_id}" class="btn" style="text-decoration: none; padding: 8px 16px; font-size: 13px;">Edit</a>
                <button onclick="confirmDelete()" class="btn" style="margin-left: 8px; padding: 8px 12px;"><span class="material-icons" style="font-size: 16px; vertical-align: middle;">delete</span></button>
            </div>
        </div>
        {rating_section}
        {tags_section}
        {source_html}
        <p><strong>Total footprint:</strong> {r.get('total_co2', 0):.2f} kg CO2e · <strong>Servings:</strong> {r.get('servings', 1):.0f}</p>

        {original_ing_html}

        <h2 style="margin-top: 32px;">Per Serving</h2>
        <table>
            <tr><td>CO2</td><td>{r.get('co2_per_serving', 0):.2f} kg</td></tr>
            <tr><td>Calories</td><td>{kcal:.0f} kcal</td></tr>
            <tr><td>Fat</td><td>{fat:.1f} g</td></tr>
            <tr><td>Carbs</td><td>{carbs:.1f} g</td></tr>
            <tr><td>Protein</td><td>{protein:.1f} g</td></tr>
        </table>

        {notes_html}

        <details style="margin-top: 32px;">
            <summary style="cursor: pointer; font-weight: 500; color: #1976D2;">Calculated Ingredients</summary>
            <table style="margin-top: 12px;">
                <tr>
                    <th>Ingredient</th>
                    <th>Weight</th>
                    <th>CO2</th>
                </tr>
                {ingredients_rows}
            </table>
        </details>

        <hr class="divider">
        <a href="/history">← Back to all recipes</a>
    </div>

    <script>
    function confirmDelete() {{
        if (confirm('Are you sure you want to delete this recipe?')) {{
            window.location.href = '/delete/{recipe_id}';
        }}
    }}
    </script>
    """

@app.route('/edit/<recipe_id>')
def edit(recipe_id):
    import os

    if not os.path.exists('recipes.json'):
        return f"""
        {MATERIAL_CSS}
        {NAV_BAR}
        <div class="card">
            <h1>Recipe not found</h1>
            <a href="/history">← Back to all recipes</a>
        </div>
        """

    with open('recipes.json', 'r') as f:
        recipes = json.load(f)

    r = next((recipe for recipe in recipes if recipe.get('id') == recipe_id), None)
    if not r:
        return f"""
        {MATERIAL_CSS}
        {NAV_BAR}
        <div class="card">
            <h1>Recipe not found</h1>
            <a href="/history">← Back to all recipes</a>
        </div>
        """

    # Build datalist options (all ingredients from DB)
    all_ingredients = sorted(df['Name'].unique().tolist())
    datalist_options = "".join([f'<option value="{name}">' for name in all_ingredients])

    # Available units
    available_units = list(CONVERSIONS['units'].keys())

    # Build ingredient rows from saved data
    rows_html = ""
    for idx, ing in enumerate(r.get('ingredients', [])):
        item_name = ing.get('item', '')
        amount = ing.get('amount', 0)
        unit = ing.get('unit', 'g')

        # Build unit dropdown
        unit_options = "".join([
            f'<option value="{u}" {"selected" if u == unit else ""}>{u}</option>'
            for u in available_units
        ])

        datalist_id = f"ingredients_{idx}"

        rows_html += f"""
        <tr style="border-bottom: 1px solid #ddd;">
            <td style="padding: 15px; width: 35%">
                <input type="number" name="amounts" value="{amount}" step="any" style="width: 80px; padding: 8px; margin-right: 8px;" required>
                <select name="units" style="width: 80px; padding: 8px;">
                    {unit_options}
                </select>
            </td>
            <td style="padding: 15px; width: 5%; text-align: center;">&rarr;</td>
            <td style="padding: 15px; width: 55%;">
                <input type="text" name="selected_matches" list="{datalist_id}" value="{item_name}" style="width: 300px;" required>
                <datalist id="{datalist_id}">{datalist_options}</datalist>
            </td>
            <td style="padding: 15px; width: 5%;">
                <button type="button" onclick="this.closest('tr').remove();" style="color: red; border: none; background: none; cursor: pointer; font-size: 20px;">&times;</button>
            </td>
        </tr>
        """

    # Current tags as comma-separated string
    tags_str = ", ".join(r.get('tags', []))
    source_str = r.get('source', '')
    notes_str = r.get('notes', '')
    original_ingredients_str = r.get('original_ingredients', '')

    # Build unit options and ingredients for JavaScript
    unit_options_js = json.dumps(available_units)
    ingredients_js = json.dumps(all_ingredients)

    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card">
        <h2>Edit Recipe</h2>
        <form method="POST" action="/update/{recipe_id}">
            <label>Recipe Name</label>
            <input type="text" name="recipe_name" value="{html.escape(r['name'])}" required>
            <br><br>
            <label>Servings</label>
            <input type="number" name="servings" value="{r.get('servings', 1)}" step="0.1" required>
            <br><br>

            <label>Ingredients</label>
            <table id="ingredients-table">
                {rows_html}
            </table>
            <button type="button" class="btn" onclick="addIngredientRow()" style="margin-top: 12px;">+ Add Ingredient</button>
            <br><br>

            <label>Source</label>
            <input type="text" name="source" value="{html.escape(source_str)}" placeholder="URL, cookbook, or 'Family recipe'">
            <br><br>

            <label>Tags (comma-separated)</label>
            <input type="text" name="tags" value="{html.escape(tags_str)}" placeholder="dinner, quick, comfort-food">
            <br><br>

            <label>Original Ingredients</label>
            <textarea name="original_ingredients" rows="6" style="font-size: 14px;">{html.escape(original_ingredients_str)}</textarea>
            <br><br>

            <label>Instructions</label>
            <textarea name="notes" rows="8" style="font-size: 14px;">{html.escape(notes_str)}</textarea>
            <br><br>

            <button type="submit" class="btn btn-success">Save Changes</button>
            <a href="/recipe/{recipe_id}" style="margin-left: 12px;">Cancel</a>
        </form>
    </div>

    <script>
    const availableUnits = {unit_options_js};
    const allIngredients = {ingredients_js};
    let rowCounter = 1000;

    function addIngredientRow() {{
        rowCounter++;
        const table = document.getElementById('ingredients-table');

        const unitOptions = availableUnits.map(u => `<option value="${{u}}">${{u}}</option>`).join('');
        const datalistId = `ingredients_${{rowCounter}}`;
        const datalistOptions = allIngredients.map(name => `<option value="${{name}}">`).join('');

        const row = document.createElement('tr');
        row.style.borderBottom = '1px solid #ddd';
        row.innerHTML = `
            <td style="padding: 15px; width: 35%">
                <input type="number" name="amounts" value="100" step="any" style="width: 80px; padding: 8px; margin-right: 8px;" required>
                <select name="units" style="width: 80px; padding: 8px;">
                    ${{unitOptions}}
                </select>
            </td>
            <td style="padding: 15px; width: 5%; text-align: center;">&rarr;</td>
            <td style="padding: 15px; width: 55%;">
                <input type="text" name="selected_matches" list="${{datalistId}}" placeholder="Search ingredient..." style="width: 300px;" required>
                <datalist id="${{datalistId}}">${{datalistOptions}}</datalist>
            </td>
            <td style="padding: 15px; width: 5%;">
                <button type="button" onclick="this.closest('tr').remove();" style="color: red; border: none; background: none; cursor: pointer; font-size: 20px;">&times;</button>
            </td>
        `;

        table.appendChild(row);
    }}
    </script>
    """

@app.route('/update/<recipe_id>', methods=['POST'])
def update(recipe_id):
    import os

    if not os.path.exists('recipes.json'):
        return "Recipe not found", 404

    with open('recipes.json', 'r') as f:
        recipes = json.load(f)

    # Find recipe index
    recipe_idx = next((i for i, recipe in enumerate(recipes) if recipe.get('id') == recipe_id), None)
    if recipe_idx is None:
        return "Recipe not found", 404

    # Get form data
    recipe_name = request.form.get('recipe_name')
    servings = float(request.form.get('servings', 1))
    amounts = request.form.getlist('amounts')
    units = request.form.getlist('units')
    selected_matches = request.form.getlist('selected_matches')

    # Parse tags
    tags_raw = request.form.get('tags', '')
    tags = [tag.strip() for tag in tags_raw.split(',') if tag.strip()]

    # Get source, notes, and original ingredients
    source = request.form.get('source', '')
    notes = request.form.get('notes', '')
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

        # Look up from DB
        db_match = df[df['Name'] == match_name]
        if db_match.empty:
            continue

        db_row = db_match.iloc[0]
        co2_val = db_row['Total kg CO2-eq/kg']

        grams = get_weight_in_grams(amt, unit, match_name)
        item_co2 = (grams / 1000) * co2_val
        total_co2 += item_co2

        # Nutrition
        energy_kj = db_row['Energy (KJ/100 g)'] if pd.notna(db_row['Energy (KJ/100 g)']) else 0
        fat = db_row['Fat (g/100 g)'] if pd.notna(db_row['Fat (g/100 g)']) else 0
        carbs = db_row['Carbohydrate (g/100 g)'] if pd.notna(db_row['Carbohydrate (g/100 g)']) else 0
        protein = db_row['Protein (g/100 g)'] if pd.notna(db_row['Protein (g/100 g)']) else 0

        total_kcal += (grams / 100) * (energy_kj / 4.184)
        total_fat += (grams / 100) * fat
        total_carbs += (grams / 100) * carbs
        total_protein += (grams / 100) * protein

        detailed_ingredients.append({
            "item": match_name,
            "amount": amt,
            "unit": unit,
            "match": match_name,
            "grams": round(grams, 1),
            "co2": round(item_co2, 3)
        })

    # Calculate CO2 per serving and rating
    co2_per_serving = round(total_co2 / servings, 3) if servings > 0 else 0
    rating = calculate_rating(co2_per_serving)

    # Update the recipe
    recipes[recipe_idx]['name'] = recipe_name
    recipes[recipe_idx]['servings'] = servings
    recipes[recipe_idx]['total_co2'] = round(total_co2, 3)
    recipes[recipe_idx]['co2_per_serving'] = co2_per_serving
    recipes[recipe_idx]['rating'] = rating
    recipes[recipe_idx]['ingredients'] = detailed_ingredients
    recipes[recipe_idx]['tags'] = tags
    recipes[recipe_idx]['source'] = source
    recipes[recipe_idx]['notes'] = notes
    recipes[recipe_idx]['original_ingredients'] = original_ingredients
    recipes[recipe_idx]['metadata']['nutrition'] = {
        "kcal": round(total_kcal / servings, 0) if servings > 0 else 0,
        "fat": round(total_fat / servings, 1) if servings > 0 else 0,
        "carbs": round(total_carbs / servings, 1) if servings > 0 else 0,
        "protein": round(total_protein / servings, 1) if servings > 0 else 0
    }

    # Save back to file
    with open('recipes.json', 'w') as f:
        json.dump(recipes, f, indent=4)

    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card" style="text-align: center;">
        <h1>Updated!</h1>
        <p><strong>{recipe_name}</strong> has been saved.</p>
        <br>
        <a href="/recipe/{recipe_id}" class="btn" style="display: inline-block; text-decoration: none;">View Recipe</a>
    </div>
    """

@app.route('/delete/<recipe_id>')
def delete(recipe_id):
    import os

    if not os.path.exists('recipes.json'):
        return "Recipe not found", 404

    with open('recipes.json', 'r') as f:
        recipes = json.load(f)

    # Find and remove recipe
    recipes = [r for r in recipes if r.get('id') != recipe_id]

    # Save back to file
    with open('recipes.json', 'w') as f:
        json.dump(recipes, f, indent=4)

    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <div class="card" style="text-align: center;">
        <h1>Deleted</h1>
        <p>The recipe has been removed.</p>
        <br>
        <a href="/history" class="btn" style="display: inline-block; text-decoration: none;">View All Recipes</a>
    </div>
    """

@app.route('/about-rating')
def about_rating():
    return f"""
    {MATERIAL_CSS}
    {NAV_BAR}
    <style>
        .content h2 {{ color: #1976D2; margin-top: 32px; font-weight: 400; }}
        .content h3 {{ color: #333; margin-top: 24px; font-weight: 500; }}
        .content p {{ line-height: 1.7; color: #444; }}
        .content table {{ margin: 16px 0; }}
        .content td, .content th {{ padding: 10px 16px; }}
        .highlight {{ background: #e3f2fd; padding: 16px; border-radius: 8px; margin: 16px 0; }}
        .rating-example {{ display: inline-block; padding: 6px 14px; border-radius: 16px; color: white; font-weight: 500; font-size: 14px; margin: 4px; }}
        sup {{ font-size: 11px; color: #1976D2; }}
        .refs {{ font-size: 13px; color: #666; line-height: 1.8; }}
        .refs a {{ word-break: break-all; }}
    </style>
    <div class="card content" style="max-width: 900px;">
        <h1>Understanding the Carbon Footprint of Meals</h1>
        <p style="color: #666; font-style: italic;">Benchmarks and the Context Problem</p>

        <div style="background: #fafafa; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin: 24px 0;">
            <h3 style="margin-top: 0; color: #1976D2;">How Mealprint Rates Your Meals</h3>
            <p style="margin-bottom: 12px;">Mealprint uses traffic-light indicators based on CO<sub>2</sub> per serving:</p>
            <div style="margin: 12px 0;">
                <span class="rating-example" style="background: #4CAF50;">🟢 Very Low Footprint</span> Less than 0.4 kg CO<sub>2</sub>e
            </div>
            <div style="margin: 12px 0;">
                <span class="rating-example" style="background: #4CAF50;">🟢 Low Footprint</span> 0.4 – 1.0 kg CO<sub>2</sub>e
            </div>
            <div style="margin: 12px 0;">
                <span class="rating-example" style="background: #FFC107; color: #333;">🟡 Medium Footprint</span> 1.0 – 1.8 kg CO<sub>2</sub>e
            </div>
            <div style="margin: 12px 0;">
                <span class="rating-example" style="background: #f44336;">🔴 High Footprint</span> 1.8 – 2.5 kg CO<sub>2</sub>e
            </div>
            <div style="margin: 12px 0;">
                <span class="rating-example" style="background: #f44336;">🔴 Very High Footprint</span> More than 2.5 kg CO<sub>2</sub>e
            </div>
        </div>

        <h2>Introduction</h2>
        <p>The global food system accounts for between 25-30% of human-caused greenhouse gas emissions.<sup>1</sup> As individuals seek to reduce their environmental impact, understanding the carbon footprint of individual meals has become increasingly important.</p>

        <p>However, meal-level carbon footprints vary dramatically: a veggie burrito might generate 355g CO<sub>2</sub>-equivalent (CO<sub>2</sub>e), while a beef burrito with cheese and sour cream produces 3,493g CO<sub>2</sub>e—nearly ten times higher.<sup>2</sup></p>

        <p>This variation creates a challenge: without clear benchmarks, consumers cannot determine whether a given meal's footprint is high, low, or somewhere in between. A number like "1,200g CO<sub>2</sub>e" is meaningless without context.</p>

        <h2>Benchmarks: What's a Sustainable Meal?</h2>

        <h3>Daily and Annual Targets</h3>
        <p>Research has established several thresholds for sustainable dietary carbon footprints. The Harvard Foodprint Calculator identifies <strong>680kg CO<sub>2</sub>e per year</strong> as the upper limit of a sustainable diet.<sup>3</sup> This translates to approximately 1,863g CO<sub>2</sub>e per day, or roughly <strong>620g per meal</strong> assuming three meals daily.</p>

        <p>The Paris Climate Accord established a more lenient target: approximately <strong>921g per meal</strong>.<sup>2</sup> While higher than the sustainable threshold, this represents a significant reduction from current dietary patterns.</p>

        <h3>Actual Diet Footprints</h3>
        <p>Current dietary patterns show substantial variation:</p>
        <ul>
            <li><strong>Meat-lover diet:</strong> ~3,300kg CO<sub>2</sub>e annually (4x the sustainable threshold)<sup>4</sup></li>
            <li><strong>Vegetarian diet:</strong> ~1,650kg per year</li>
            <li><strong>Vegan diet:</strong> ~1,500kg annually</li>
        </ul>

        <h3>Concrete Meal Examples</h3>
        <table>
            <tr><th>Meal</th><th>CO<sub>2</sub>e (grams)</th></tr>
            <tr><td>Beef burrito (beef, cheese, sour cream, rice)</td><td><strong>3,493</strong></td></tr>
            <tr><td>Impossible burrito (plant-based meat, guacamole, rice)</td><td><strong>581</strong></td></tr>
            <tr><td>Veggie burrito (beans, guacamole, rice)</td><td><strong>355</strong></td></tr>
        </table>
        <p style="font-size: 13px; color: #666;">Source: UCLA carbon footprint research<sup>2</sup></p>

        <h2>Key Drivers</h2>
        <p>Ingredient choice dominates meal carbon footprints. Beef production generates approximately <strong>60kg CO<sub>2</sub>e per kilogram</strong>, while peas produce just <strong>1kg CO<sub>2</sub>e per kilogram</strong>—a 60-fold difference.<sup>6</sup></p>

        <div class="highlight">
            <strong>Key insight:</strong> Transportation accounts for less than 5% of most foods' carbon footprints. Ingredient selection matters far more than food miles.<sup>6</sup>
        </div>

        <h2>How Mealprint Rates Your Meals</h2>

        <h3>Current Approach: Absolute Thresholds</h3>
        <p>Mealprint currently uses simple traffic-light indicators based on CO<sub>2</sub> per serving:</p>

        <div style="margin: 20px 0;">
            <span class="rating-example" style="background: #4CAF50;">🟢 Very Low Footprint</span> Less than 0.4 kg CO<sub>2</sub>e
        </div>
        <div style="margin: 20px 0;">
            <span class="rating-example" style="background: #4CAF50;">🟢 Low Footprint</span> 0.4 – 1.0 kg CO<sub>2</sub>e
        </div>
        <div style="margin: 20px 0;">
            <span class="rating-example" style="background: #FFC107; color: #333;">🟡 Medium Footprint</span> 1.0 – 1.8 kg CO<sub>2</sub>e
        </div>
        <div style="margin: 20px 0;">
            <span class="rating-example" style="background: #f44336;">🔴 High Footprint</span> 1.8 – 2.5 kg CO<sub>2</sub>e
        </div>
        <div style="margin: 20px 0;">
            <span class="rating-example" style="background: #f44336;">🔴 Very High Footprint</span> More than 2.5 kg CO<sub>2</sub>e
        </div>

        <h3>Future: Category-Specific Ratings</h3>
        <p>Absolute thresholds have a limitation: they ignore meal context. A 400g dessert might be rated "low" even though it's high for a dessert, while a 1,200g vegetable stir-fry dinner might be rated "medium" despite being low-carbon for a main meal.</p>

        <p>Once Mealprint has sufficient recipes in each category, ratings will transition to <strong>percentile-based comparisons within meal types</strong>—so you'll see how your dessert compares to other desserts, not to all meals.</p>

        <h2>References</h2>
        <ol class="refs">
            <li>University of Michigan Center for Sustainable Systems. (2025). Carbon Footprint Factsheet.</li>
            <li>UCLA Dining. Fight Climate Change with Food. <a href="https://dining.ucla.edu/carbonfootprint/" target="_blank">dining.ucla.edu/carbonfootprint</a></li>
            <li>Harvard Foodprint Calculator. <a href="https://harvard-foodprint-calculator.github.io/" target="_blank">harvard-foodprint-calculator.github.io</a></li>
            <li>Green Eatz. (2022). How to Lower Your Food's Carbon Footprint.</li>
            <li>Blackstone, N. T., et al. (2021). The carbon footprint of dietary guidelines around the world. <em>Nutrition Journal</em>, 20(1), 15.</li>
            <li>Ritchie, H. (2020). You want to reduce the carbon footprint of your food? Focus on what you eat, not whether your food is local. <a href="https://ourworldindata.org/food-choice-vs-eating-local" target="_blank">Our World in Data</a></li>
        </ol>

        <hr class="divider">
        <a href="javascript:history.back()">← Go back</a>
    </div>
    """

# This MUST be at the very bottom of the file
if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    app.run(debug=debug_mode, port=8080)
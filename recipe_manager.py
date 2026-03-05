import json
import os
import uuid

# Load configuration from JSON files
CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'config')

def load_json_config(filename):
    filepath = os.path.join(CONFIG_DIR, filename)
    with open(filepath, 'r') as f:
        return json.load(f)

# Load units configuration
_units_config = load_json_config('units.json')
CONVERSIONS = {
    "units": _units_config['conversions'],
    "ingredients": _units_config['ingredient_weights']
}
UNIT_MAP = _units_config['unit_map']

# Load ingredient aliases
_aliases_config = load_json_config('ingredient_aliases.json')
INGREDIENT_ALIASES = _aliases_config['aliases']

# Load density configuration for volume-to-weight conversions
DENSITIES = load_json_config('densities.json')

# Volume units that need density conversion (ml-based)
VOLUME_UNITS = {'ml', 'dl', 'l', 'cup', 'tbsp', 'tsp', 'drop', 'pinch', 'dash', 'quart', 'fl oz'}

def get_density(ingredient_name):
    """
    Get density (g/ml) for ingredient based on keyword matching.
    Returns density multiplier for converting ml to grams.
    """
    name_lower = ingredient_name.lower()

    for category, config in DENSITIES['categories'].items():
        # Check exclusions first
        if any(excl in name_lower for excl in config.get('exclude', [])):
            continue
        # Check keywords
        if any(kw in name_lower for kw in config['keywords']):
            return config['density']

    return DENSITIES['default_density']

def get_density_category(ingredient_name):
    """Return the density category name for an ingredient, for use in transparency reports."""
    name_lower = ingredient_name.lower()
    for category, config in DENSITIES['categories'].items():
        if any(excl in name_lower for excl in config.get('exclude', [])):
            continue
        if any(kw in name_lower for kw in config['keywords']):
            return category.replace('_', ' ')
    return None

def get_weight_in_grams(amount, unit, ingredient_name="", original_name=""):
    """
    Convert amount + unit to grams.
    - Volume units (cup, tbsp, ml, etc.) apply ingredient-specific density
    - Weight units (g, kg, lb, oz) convert directly
    - Piece units look up ingredient weights

    original_name: the ingredient text before alias substitution (e.g. "2 egg yolks").
    Used for piece weight lookup so "egg yolk" (18g) beats the generic "egg" (60g) match.
    """
    name = ingredient_name.lower()
    # For piece weight lookup, prefer original text — it's more specific than the DB name.
    # e.g. "egg yolk" in original beats "egg" matching "eggs, chicken" in DB name.
    lookup_name = original_name.lower() if original_name else name
    clean_unit = UNIT_MAP.get(unit.lower(), unit.lower())

    # Volume units: convert to ml first, then apply density
    if clean_unit in VOLUME_UNITS:
        ml_value = amount * CONVERSIONS["units"][clean_unit]
        density = get_density(ingredient_name)
        return ml_value * density

    # Weight units (g, kg, lb, oz): direct conversion
    if clean_unit in CONVERSIONS["units"] and clean_unit not in ["piece", "pcs", "unit", "handful", "sprinkling"]:
        return amount * CONVERSIONS["units"][clean_unit]

    # Fixed weight units (handful, sprinkling) - no density needed
    if clean_unit in ["handful", "sprinkling"]:
        return amount * CONVERSIONS["units"][clean_unit]

    # Piece units: lookup ingredient weight.
    # Sort keys longest-first so specific entries ("egg yolk") win over general ones ("egg").
    if clean_unit in ["piece", "pcs", "unit", "can"]:
        # Cans: check for ingredient-specific can weight first, then fall back to 400g
        if clean_unit == "can":
            for key in sorted(CONVERSIONS["ingredients"].keys(), key=len, reverse=True):
                if key in lookup_name or key in name:
                    return amount * CONVERSIONS["ingredients"][key]
            return amount * CONVERSIONS["ingredients"].get("can", 400)
        for key in sorted(CONVERSIONS["ingredients"].keys(), key=len, reverse=True):
            if key in lookup_name or key in name:
                return amount * CONVERSIONS["ingredients"][key]
        return amount * CONVERSIONS["units"]["piece"]

    # Unknown unit - return 0
    return 0

FILENAME = "recipes.json"

def calculate_rating(co2_per_serving):
    """
    Calculate carbon footprint rating based on CO2 per serving (in kg).
    Returns dict with rating label, color, and emoji.

    Thresholds:
    - Very Low (Green): < 0.4 kg
    - Low (Green): 0.4 - 1.0 kg
    - Medium (Yellow): 1.0 - 1.8 kg
    - High (Red): 1.8 - 2.5 kg
    - Very High (Red): > 2.5 kg
    """
    if co2_per_serving < 0.4:
        return {"label": "Very Low", "color": "#4CAF50", "emoji": "🟢"}
    elif co2_per_serving < 1.0:
        return {"label": "Low", "color": "#4CAF50", "emoji": "🟢"}
    elif co2_per_serving < 1.8:
        return {"label": "Medium", "color": "#FFC107", "emoji": "🟡"}
    elif co2_per_serving < 2.5:
        return {"label": "High", "color": "#f44336", "emoji": "🔴"}
    else:
        return {"label": "Very High", "color": "#f44336", "emoji": "🔴"}

def save_recipe(recipe_name, ingredients, total_co2, servings, nutrition=None, tags=None, source=None, notes=None, original_ingredients=None):
    co2_per_serving = round(total_co2 / servings, 3)
    rating = calculate_rating(co2_per_serving)

    new_recipe = {
        "id": str(uuid.uuid4()),
        "name": recipe_name,
        "total_co2": round(total_co2, 3),
        "servings": servings,
        "co2_per_serving": co2_per_serving,
        "ingredients": ingredients,
        "tags": tags or [],
        "source": source or "",
        "notes": notes or "",
        "original_ingredients": original_ingredients or "",
        "rating": rating,
        "metadata": {
            "nutrition": nutrition or {}
        }
    }

    if os.path.exists(FILENAME):
        with open(FILENAME, "r") as f:
            all_recipes = json.load(f)
    else:
        all_recipes = []

    all_recipes.append(new_recipe)
    with open(FILENAME, "w") as f:
        json.dump(all_recipes, f, indent=4)

    print(f"\nRecipe '{recipe_name}' saved to {FILENAME}!")

def list_recipes():
        # Check if the file actually exists before trying to open it
        if os.path.exists(FILENAME):
            with open(FILENAME, "r") as f:
                all_recipes = json.load(f)
                print("\n--- YOUR SAVED RECIPES ---")
                # Loop through every recipe in our list one by one
                for r in all_recipes:
                    impact = r.get('co2_per_serving', 0.0) 
                    print(f"Recipe: {r['name']} | Impact: {impact} kg/serving")

        else:
            print("No recipes saved yet.")

def find_best_match(z_search_text_z, df):
    # We force it to be a string right here
    final_string = str(z_search_text_z).strip()
    
    # 1. Exact match
    exact_match = df[df['Name'].str.lower() == final_string.lower()]
    if not exact_match.empty:
        return exact_match.iloc[0].to_dict()
    
    # 2. Starts with
    starts_with = df[df['Name'].str.contains(f"^{final_string}", case=False, na=False, regex=True)]
    if not starts_with.empty:
        return starts_with.iloc[0].to_dict()

    # 3. Contains
    contains = df[df['Name'].str.contains(final_string, case=False, na=False, regex=False)]
    if not contains.empty:
        return contains.iloc[0].to_dict()
    
    return None
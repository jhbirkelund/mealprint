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

def get_weight_in_grams(amount, unit, ingredient_name=""):
    name = ingredient_name.lower()
    clean_unit = UNIT_MAP.get(unit.lower(), unit.lower())

    # If it's a standard unit (g, kg, cup, etc.), just do the math
    if clean_unit in CONVERSIONS["units"] and clean_unit not in ["piece", "pcs", "unit"]:
        return amount * CONVERSIONS["units"][clean_unit]
    
    # Check if the unit is 'pieces' look for a keyword match
    if clean_unit in ["piece", "pcs", "unit"]:
        for key in CONVERSIONS["ingredients"]:
            if key in name:
                return amount * CONVERSIONS["ingredients"][key]

        # If the ingredient isn't in list, fall back to 100g
        item_weight = CONVERSIONS["ingredients"].get(ingredient_name.lower(), CONVERSIONS["units"]["piece"])
        return amount * item_weight
    
    #If the unit is totally unknown, return 0
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
import pandas as pd
import json
from recipe_scrapers import scrape_me
from quantulum3 import parser
from recipe_manager import get_weight_in_grams, UNIT_MAP, find_best_match

# 1. Setup
url = 'https://www.bbcgoodfood.com/recipes/ultimate-spaghetti-carbonara-recipe'
scraper = scrape_me(url)
df = pd.read_excel('climate_data.xlsx', sheet_name='DK')

print(f"Analysing: {scraper.title()}\n")

# 1. Start the counter at zero
total_recipe_co2 = 0
all_ingredients = []

for line in scraper.ingredients():
    # 2. Extract Amount, Unit and Name
    quants = parser.parse(line)
    if quants:
        amt = quants[0].value
        # Translate the unit using our map, default to piece if unknown
        unit = UNIT_MAP.get(quants[0].unit.name, "piece")
        
        raw_Text = str(line.replace(str(quants[0].surface), "").strip().split(',')[0]) # split avoids 'salt, or more to taste'
    else:
        continue # Skip lines we can't read

    # Use food_item in the function call 3. Find the CO2 match in the DB
    match = find_best_match(raw_Text, df)

    if match is not None:
        # 4. Use your existing logic to get weight and CO2
        grams = get_weight_in_grams(amt, unit, match['Name'])
        co2 = (grams / 1000) * match['Total kg CO2-eq/kg']
        total_recipe_co2 += co2

        # 5. Add to our list for JSON
        all_ingredients.append({
            "item": raw_Text,
            "amount": amt,
            "unit": unit,
            "match": match['Name'],
            "grams": grams,
            "co2": round(co2, 3)
        })


        print(f"MATCH: {raw_Text} -> {match['Name']} {co2:.3f} kg CO2)")

    else:
        print(f"MISSING: Could not find CO2 for {raw_Text}")

# After the loop finishes
recipe_name = input("\nWhat is the name of this recipe?")
servings = float(input("\nHow many servings does this recipe make? "))

# Calculate footprint per serving
footprint_per_serving = total_recipe_co2 / servings if servings > 0 else 0

# Create recipe JSON
recipe_data = {
    "name": recipe_name,
    "servings": servings,
    "total_co2": round(total_recipe_co2, 3),
    "co2_per_serving": round(footprint_per_serving, 3),
    "ingredients": all_ingredients
}

# Show recipe overview
print(f"Recipe: {recipe_name}")
print(f"Total footprint: {total_recipe_co2:.2f} kg CO2")
print(f"Servings: {servings}")
print(f"Footpring per serving: {footprint_per_serving:.2f} kg CO2")
print(f"Ingredients matched: {len(all_ingredients)}")

# Save to JSON
save_choice = input("\nDo you want to save to database? (y/n): ").lower().strip()

if save_choice == 'y':
    try:
        with open("recipes.json", "r") as f:
            all_recipes = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        all_recipes = []

    all_recipes.append(recipe_data)

    with open("recipes.json", "w") as f:
        json.dump(all_recipes, f, indent=4)

    print(f"{recipe_name} has been saved to recipes.json")

else:
    print("Save cancelled.")


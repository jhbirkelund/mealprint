import pandas as pd

# First, import our new list function at the top
from recipe_manager import save_recipe, list_recipes

print("--- Mealprint Main Menu ---")
print("1. Create New Meal")
print("2. View Saved Recipes")

choice = input("Select an option: ")

if choice == "2":
    list_recipes()
else:
    # The existing "while True" loop and logic follows:
    print("\nStarting Meal Builder")

    # The meal builder logic:

    df = pd.read_excel('climate_data.xlsx', sheet_name='DK')

    meal_ingredients = []   # A list to store our items
    total_meal_co2 = 0      # A counter for the sum

    print("--- Mealprint Ingredient Tracker ---")

    while True:
        user_input = input("\nSearch food or 'done' to finish: ").strip().lower()

        if user_input == 'done':
            break

        results = df[df['Name'].str.contains(user_input, case=False, na=False)]

        if not results.empty:
            print(results[['Name', 'Total kg CO2-eq/kg']].reset_index(drop=True))
            try:
                choice = int(input("Enter index number: "))
                selected_item = results.iloc[choice]
            except (ValueError, IndexError):
                print("Invalid selection. Please enter a valid number from the list.")
                continue # This jumps back to the start of the loop
            
            # Ask for the amount (the number)
            amount = float(input(f"How much {selected_item['Name']}: "))
            
            # Ask for the unit:
            unit = input("Enter unit (g, kg, ml, l, cup, piece): ").lower()

            # Use the translator to get grams
            from recipe_manager import get_weight_in_grams
            weight_in_grams = get_weight_in_grams(amount, unit, selected_item['Name'])

            # Use the new weight_in_grams for the CO2 calculation
            weight_in_kg = weight_in_grams / 1000
            item_co2 = weight_in_kg * selected_item['Total kg CO2-eq/kg']

            total_meal_co2 += item_co2
            # We save a dictionary of info to our list
            meal_ingredients.append({
                "name": selected_item['Name'],
                "display_amount": f"{amount} {unit}",
                "grams": weight_in_grams,
                "co2": item_co2
            })

        else:
            print("Not found.")

    print("\nFINAL MEAL SUMMARY:")
    for item in meal_ingredients:
        print(f"- {item['display_amount']} {item['name']}: {item['co2']:.3f} kg CO2-eq")

    print(f"TOTAL FOOTPRINT: {total_meal_co2:.2f} kg CO2-eq")

    # Ask the user if they want to save
    save_prompt = input("Do you want to save this recipe? (y/n): ").lower()

    if save_prompt == 'y':
        recipe_name = input("Enter a name for this recipe: ")
        servings = int(input("How many servings does this recipe make? "))
        # This calls the function from your other file
        save_recipe(recipe_name, meal_ingredients, total_meal_co2, servings)
            
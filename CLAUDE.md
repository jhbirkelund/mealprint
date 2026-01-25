# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mealprint is a Python application for calculating the carbon footprint (CO2 emissions) of recipes based on ingredient composition. It provides three interfaces: a Flask web application, a CLI tool, and an automated web scraper.

## Running the Application

```bash
# Web application (primary interface) - runs on http://localhost:8080
python manual_app.py

# CLI meal builder
python meal_builder.py

# Automated recipe scraper (extracts recipes from URLs)
python auto_builder.py
```

## Architecture

### Core Components

- **manual_app.py** - Flask web app with routes:
  - `/` - Recipe input (manual or URL scrape)
  - `/scrape` - Extracts recipe from URL, auto-populates form
  - `/summary` - Ingredient correction UI with editable amounts/units and "Add ingredient" button
  - `/calculate` - CO2 + nutrition calculation with preview
  - `/save/` - Persists recipe to JSON
  - `/history` - All saved recipes list
  - `/recipe/<uuid>` - Individual recipe view (original ingredients, nutrition, instructions, collapsible calculated table)
  - `/edit/<uuid>` - Edit recipe (reuses summary-style UI)
  - `/update/<uuid>` - Saves recipe edits
  - `/delete/<uuid>` - Deletes recipe (with confirmation)

  Uses f-string HTML generation with Material Design styling + Google Material Icons. Ingredient matching uses a hybrid approach: token-based word matching + rapidfuzz fuzzy matching, displaying multiple candidates in a dropdown for user selection.

- **recipe_manager.py** - Shared utilities module containing:
  - `save_recipe()` - Persists recipes to recipes.json with full schema (id, tags, source, notes, original_ingredients, nutrition)
  - `list_recipes()` - Displays saved recipes
  - `get_weight_in_grams()` - Converts various units to standard grams (handles ingredient-specific weights like eggs=60g)
  - `find_best_match()` - Fuzzy matches food names to climate database (priority: exact → starts with → contains)
  - `CONVERSIONS` - Unit multipliers (g, kg, ml, l, tsp, tbsp, cup, lb, oz, drop, pinch, piece) and ingredient weights (egg, onion, tomato, garlic, bell pepper, bouillon cube)
  - `UNIT_MAP` - Maps unit variations to standardized keys (e.g., "pounds" → "lb", "tablespoons" → "tbsp")

- **meal_builder.py** - Interactive CLI with text-based menu for creating and viewing recipes

- **auto_builder.py** - Uses recipe_scrapers library to extract recipes from URLs, then processes them through the CO2 calculation pipeline

### Data Flow

1. **Input**: User enters recipe manually OR scrapes from URL (extracts title, servings, ingredients, instructions)
2. **Parse**: quantulum3 extracts quantities and units from ingredient text
3. **Match**: Hybrid matching (token-based + rapidfuzz) suggests DB ingredients; user confirms/corrects
4. **Calculate**: Convert to grams → lookup CO2-eq/kg and nutrition → sum totals
5. **Save**: Store to recipes.json with UUID, tags, source, notes, original ingredients

### Data Files

- **climate_data.xlsx** - Environmental impact database with CO2-eq/kg values and nutrition data (Energy KJ, Fat, Carbs, Protein per 100g). Uses 'DK' sheet.
- **recipes.json** - JSON array storing recipes with structure:
  ```json
  {
    "id": "uuid-string",
    "name": "Recipe Name",
    "total_co2": 1.234,
    "servings": 4,
    "co2_per_serving": 0.309,
    "ingredients": [{"item": "...", "amount": 200, "unit": "g", "grams": 200, "co2": 0.5}],
    "tags": ["dinner", "quick"],
    "source": "https://... or 'Family recipe'",
    "notes": "Instructions text",
    "original_ingredients": "Original ingredient list as entered",
    "metadata": {"rating": null, "nutrition": {"kcal": 450, "fat": 12, "carbs": 30, "protein": 25}}
  }
  ```

### Config Files (config/)

- **units.json** - Unit conversions (g, kg, lb, oz, cup, etc.), ingredient weights (egg, onion, etc.), and unit name mappings
- **ingredient_aliases.json** - Maps common recipe terms to DB names (e.g., "ground beef" → "Beef, mince", dried herbs → "Basil, dried")

## Dependencies

- pandas - Excel data handling for climate_data.xlsx
- flask - Web framework
- quantulum3 - Parses quantities from natural language text (e.g., "200g beef")
- recipe_scrapers - Extracts recipe data from website URLs
- rapidfuzz - Fast fuzzy string matching for ingredient lookup

## Vision & Long-term Goals
- **Project Goal:** Automate recipe carbon footprinting to empower sustainable food choices.
- **Next Horizon:** Multi-user web app with footprint ratings and meal recommendations.
- **Future Integration:** Building out API capabilities and automated data flows.

### Planned Improvements
- **Footprint Rating System** - Percentile-based ratings (very-low, low, medium, high, very-high) relative to recipe database
- AI-powered ingredient matching (LLM to match "lean ground beef" → "Beef, minced" with context understanding)
- Admin UI for editing config files (units.json, ingredient_aliases.json) without touching code

### Recently Completed
- UUID-based recipe identification (multi-user ready)
- Tags system for recipe categorization
- Source field (auto-populated from scraped URLs)
- Notes/instructions field (auto-populated from scraped recipes)
- Original ingredients preservation
- Full recipe editing (name, servings, ingredients, tags, source, notes)
- Recipe deletion with confirmation
- Editable amounts/units on summary page
- Add ingredient functionality
- Collapsible calculated ingredients table

## Working Guidelines (Personalized)
- **MVP Thinking:** Always build the simplest version that works first. If a task is complex, break it into tiny, verifiable steps.
- **Step-by-Step:** Do only ONE task at a time. Explain the logic in plain language before writing any code. Do not move to the next task until I say "Done" or "Go ahead."
- **Coding Style:** Prefer clear, descriptive code. Explain new concepts simply. Avoid "bootlicking" or overly long descriptions; stay succinct and precise.
- **Verification:** After each task, provide a way for me to verify it works (e.g., "Run python manual_app.py and check the new input field").
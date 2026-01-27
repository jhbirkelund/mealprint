# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mealprint is a Python application for calculating the carbon footprint (CO2 emissions) of recipes based on ingredient composition. It provides three interfaces: a Flask web application, a CLI tool, and an automated web scraper.

## Deployment

**Production**: Hosted on Render at `mealprint.onrender.com`
- Uses Gunicorn as WSGI server
- PostgreSQL database hosted on Supabase (free tier, no expiration)
- Auto-deploys from GitHub `main` branch

**Environment Variables** (configured in Render):
- `DATABASE_URL` - Supabase PostgreSQL connection string (Session Pooler)

## Running Locally

```bash
# Web application (primary interface) - runs on http://localhost:8080
python manual_app.py

# CLI meal builder
python meal_builder.py

# Automated recipe scraper (extracts recipes from URLs)
python auto_builder.py
```

**Local database**: Set `DATABASE_URL` environment variable or the app falls back to local development mode.

## Architecture

### Core Components

- **manual_app.py** - Flask web app with routes:
  - `/` - Recipe input (manual or URL scrape)
  - `/scrape` - Extracts recipe from URL, auto-populates form
  - `/summary` - Ingredient correction UI with editable amounts/units and "Add ingredient" button
  - `/calculate` - CO2 + nutrition calculation with preview
  - `/save/` - Persists recipe to database
  - `/history` - All saved recipes list
  - `/recipe/<uuid>` - Individual recipe view (original ingredients, nutrition, instructions, collapsible calculated table)
  - `/edit/<uuid>` - Edit recipe (reuses summary-style UI)
  - `/update/<uuid>` - Saves recipe edits
  - `/delete/<uuid>` - Deletes recipe (with confirmation)
  - `/about-rating` - Explains the carbon footprint rating system

  Uses Jinja2 templates with Tailwind CSS. Ingredient matching uses a hybrid approach: token-based word matching + rapidfuzz fuzzy matching, displaying multiple candidates in a dropdown for user selection. Supports both English and Danish recipes with automatic language detection.

- **db.py** - Database module for PostgreSQL (Supabase):
  - `get_connection()` - Connect using DATABASE_URL env var
  - `init_db()` - Create tables (recipes, recipe_ingredients, recipe_tags)
  - `save_recipe_to_db()` - Insert new recipe, returns recipe_id
  - `get_all_recipes()` - List all recipes with nested ingredients/tags
  - `get_recipe_by_id()` - Get single recipe by UUID
  - `update_recipe_in_db()` - Update existing recipe
  - `delete_recipe_from_db()` - Delete recipe (CASCADE deletes related data)

- **recipe_manager.py** - Shared utilities module containing:
  - `save_recipe()` - Persists recipes to recipes.json with full schema (id, tags, source, notes, original_ingredients, nutrition)
  - `list_recipes()` - Displays saved recipes
  - `get_weight_in_grams()` - Converts various units to standard grams (handles ingredient-specific weights like eggs=60g)
  - `find_best_match()` - Fuzzy matches food names to climate database (priority: exact → starts with → contains)
  - `CONVERSIONS` - Unit multipliers (g, kg, ml, l, tsp, tbsp, cup, lb, oz, drop, pinch, piece) and ingredient weights (egg, onion, tomato, garlic, bell pepper, bouillon cube)
  - `UNIT_MAP` - Maps unit variations to standardized keys (e.g., "pounds" → "lb", "tablespoons" → "tbsp")

- **meal_builder.py** - Interactive CLI with text-based menu for creating and viewing recipes

- **auto_builder.py** - Uses recipe_scrapers library to extract recipes from URLs, then processes them through the CO2 calculation pipeline

### Templates (templates/)

Uses Jinja2 templates with Tailwind CSS (via CDN) for a modern, responsive UI:

- **base.html** - Shared layout with Tailwind, Inter font, navigation bar
- **home.html** - Recipe input page (URL scraping + manual entry)
- **summary.html** - Ingredient matching with custom autocomplete dropdown (shows candidates on focus, searches full DB on type)
- **calculate.html** - Results preview with CO2 impact before saving
- **recipe.html** - Individual recipe view with Bento Box layout
- **history.html** - Recipe list with grid cards
- **edit.html** - Edit recipe form
- **about.html** - Carbon rating explanation page

**Design System:**
- Container: `max-w-4xl mx-auto` (5xl for recipe page)
- Cards: `bg-white rounded-3xl shadow-sm border border-slate-200`
- Primary text: `text-slate-900` for headings, `text-slate-700` for body
- Accent color: `emerald-500` for buttons and interactive elements
- CO2 color coding: emerald (<1.0), amber (1.0-1.8), rose (>1.8 kg)
- Rating badges: `bg-emerald-100 text-emerald-900` (darker text for accessibility)

**Template Patterns:**
- Pass complex data to hidden form fields using single-quoted attributes: `value='{{ data | tojson }}'` (single quotes avoid conflicts with JSON's double quotes)
- Custom autocomplete: use `.ingredient-input` class with adjacent `.autocomplete-dropdown` div; JS handles filtering and selection

### Data Flow

1. **Input**: User enters recipe manually OR scrapes from URL (extracts title, servings, ingredients, instructions)
2. **Detect Language**: Auto-detect Danish (æøå, common words) vs English
3. **Parse**: Preprocess informal units (handful, sprinkling, Danish spsk/tsk) → quantulum3 extracts quantities and units
4. **Match**: Hybrid matching (token-based + rapidfuzz) against language-appropriate DB; user confirms/corrects via autocomplete
5. **Calculate**: Convert to grams → lookup CO2-eq/kg and nutrition → sum totals
6. **Save**: Store to PostgreSQL database with UUID, tags, source, notes, original ingredients

### Data Files

- **climate_data.xlsx** - English environmental impact database with CO2-eq/kg values and nutrition data (Energy KJ, Fat, Carbs, Protein per 100g). Uses 'DK' sheet.
- **climate_data_DK.xlsx** - Danish environmental impact database with same structure but Danish ingredient names (Navn, Total kg CO2e/kg, etc.). ~540 ingredients.

### Database Schema (PostgreSQL)

```sql
-- recipes table
CREATE TABLE recipes (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    total_co2 REAL,
    servings REAL,
    co2_per_serving REAL,
    source TEXT,
    notes TEXT,
    original_ingredients TEXT,
    nutrition JSONB,
    rating JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- recipe_ingredients table
CREATE TABLE recipe_ingredients (
    id SERIAL PRIMARY KEY,
    recipe_id UUID REFERENCES recipes(id) ON DELETE CASCADE,
    item TEXT,
    amount REAL,
    unit TEXT,
    grams REAL,
    co2 REAL
);

-- recipe_tags table
CREATE TABLE recipe_tags (
    id SERIAL PRIMARY KEY,
    recipe_id UUID REFERENCES recipes(id) ON DELETE CASCADE,
    tag TEXT
);
```

### Config Files (config/)

- **units.json** - Unit conversions (g, kg, lb, oz, cup, handful, sprinkling, quart, etc.), ingredient weights (egg, onion, etc.), and unit name mappings (including "pound-mass" → "lb" for quantulum3 compatibility)
- **ingredient_aliases.json** - Maps common recipe terms to DB names (e.g., "ground beef" → "Beef, mince", "shallots" → "Onion, raw", dried herbs → "Basil, dried")

## Dependencies

- flask - Web framework with Jinja2 templating
- pandas - Excel data handling for climate_data.xlsx
- quantulum3 - Parses quantities from natural language text (e.g., "200g beef")
- recipe_scrapers - Extracts recipe data from website URLs
- rapidfuzz - Fast fuzzy string matching for ingredient lookup
- psycopg2-binary - PostgreSQL database adapter
- gunicorn - Production WSGI server (for Render deployment)
- setuptools - Required for pkg_resources (quantulum3 dependency)
- openpyxl - Excel file reading

## Vision & Long-term Goals
- **Project Goal:** Automate recipe carbon footprinting to empower sustainable food choices.
- **Next Horizon:** Multi-user web app with footprint ratings and meal recommendations.
- **Future Integration:** Building out API capabilities and automated data flows.

### Planned Improvements
- **Language tag for recipes** - Store language (DK, EN) with each recipe for filtering
- **Danish language site** - Full Danish UI with language switcher (EN/DK toggle)
- **Expand Danish units and aliases** - More Danish unit mappings and ingredient_aliases_DK.json
- **Percentile-based ratings** - Compare recipes within categories (e.g., "low for a dessert")
- AI-powered ingredient matching (LLM to match "lean ground beef" → "Beef, minced" with context understanding)
- Admin UI for editing config files (units.json, ingredient_aliases.json) without touching code
- User authentication for personal recipe collections

### Recently Completed
- **Danish language support** - dual database (EN + DK), auto-detects language from æøå characters and Danish words, Danish unit preprocessing (spsk, tsk, stk, knivspids)
- **Custom autocomplete dropdown** - replaced browser datalist on summary page; shows candidates on focus, searches full DB on type, displays up to 20 results
- **Additional units** - handful (30g), sprinkling (2g), quart (946ml), fixed pound-mass mapping for quantulum3
- **Additional ingredient aliases** - shallots, double cream, tomato purée/pureé variants, whole milk
- **Improved ingredient matching** - bonus score for names starting with search term
- **Search and tag filtering on Recipes page** - search by name, filter by tags with "Show All" button
- **Info icon on recipe/calculate pages** - links to about-rating page explaining the rating system
- **Fixed JSON form encoding** - using single-quoted HTML attributes to avoid conflicts with JSON double quotes
- **Production deployment on Render** with auto-deploy from GitHub
- **PostgreSQL database on Supabase** replacing local JSON storage
- **Jinja2 templates with Tailwind CSS** replacing f-string HTML generation
- **Premium dashboard design** with Bento Box layout, big CO2 numbers, nutrition stats
- **Accessibility improvements** - better contrast (text-slate-900), card borders, darker badge text
- **Interactive recipe view** - checkboxes for ingredients/steps with strike-through effect
- **Full database search on summary page** - users can search entire climate DB, not just suggested matches
- UUID-based recipe identification (multi-user ready)
- Tags system for recipe categorization
- Source field (auto-populated from scraped URLs)
- Notes/instructions field (auto-populated from scraped recipes)
- Original ingredients preservation
- Full recipe editing (name, servings, ingredients, tags, source, notes)
- Recipe deletion with confirmation
- Editable amounts/units on summary page
- Add ingredient functionality
- Collapsible CO2 breakdown table

## Working Guidelines (Personalized)
- **MVP Thinking:** Always build the simplest version that works first. If a task is complex, break it into tiny, verifiable steps.
- **Step-by-Step:** Do only ONE task at a time. Explain the logic in plain language before writing any code. Do not move to the next task until I say "Done" or "Go ahead."
- **Coding Style:** Prefer clear, descriptive code. Explain new concepts simply. Avoid "bootlicking" or overly long descriptions; stay succinct and precise.
- **Verification:** After each task, provide a way for me to verify it works (e.g., "Run python manual_app.py and check the new input field").
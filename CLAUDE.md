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

**Local database**: Requires `DATABASE_URL` environment variable pointing to Supabase (no local fallback - all data lives in Supabase).

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

  Uses Jinja2 templates with Tailwind CSS. Ingredient matching uses a hybrid approach: token-based word matching + rapidfuzz fuzzy matching against cached `CLIMATE_NAMES` (loaded from Supabase at startup), displaying multiple candidates in a dropdown for user selection. Supports English, Danish, and French ingredient names natively through the unified climate database.

- **db.py** - Database module for PostgreSQL (Supabase):
  - `get_connection()` - Connect using DATABASE_URL env var
  - `init_db()` - Create tables (recipes, recipe_ingredients, recipe_tags, climate_ingredients, import_jobs, import_items)
  - `save_recipe_to_db()` - Insert new recipe with origin/is_published/import_job_id tracking, returns recipe_id
  - `get_all_recipes()` - List all recipes with nested ingredients/tags (includes origin, is_published)
  - `get_recipe_by_id()` - Get single recipe by UUID (includes origin, is_published)
  - `update_recipe_in_db()` - Update existing recipe
  - `delete_recipe_from_db()` - Delete recipe (CASCADE deletes related data)
  - **Climate Ingredients (Multi-Source Engine):**
    - `get_all_climate_ingredients()` - Get all ingredient names for autocomplete
    - `search_climate_ingredients(term, limit)` - Search with waterfall priority (Danish → Agribalyse)
    - `get_ingredient_by_name(name)` - Exact match lookup with confidence ranking
  - **Import Jobs (Bulk Scraping):**
    - `create_import_job(urls)` - Create job with URL list, returns job_id
    - `get_import_job(job_id)` - Get job with all items
    - `get_all_import_jobs()` - List all jobs (for admin UI)
    - `get_pending_import_items(job_id)` - Get URLs ready to process
    - `update_import_item(item_id, status)` - Update item after processing (auto-updates job counters)
    - `start_import_job(job_id)` - Mark job as processing

- **ingredient_matcher.py** - Shared ingredient matching logic:
  - `parse_ingredients(raw_text)` - Parse ingredient text, return candidates with confidence
  - `calculate_ingredient(amount, unit, name)` - Calculate CO2/nutrition for single ingredient
  - `calculate_recipe_totals(ingredients)` - Sum CO2 and nutrition for full recipe
  - `auto_match_ingredients(raw_text)` - Parse and auto-select best matches (for bulk scraper)
  - `load_climate_names()` - Load ingredient names from Supabase

- **bulk_scraper.py** - Batch recipe import tool:
  - `run_import_job(urls)` - Process URL list, save as unpublished recipes
  - `scrape_recipe(url)` - Extract recipe data from URL
  - `process_recipe(data, climate_names)` - Match ingredients and calculate CO2
  - `detect_language(text, domain)` - Simple EN/DA/FR detection
  - CLI: `python bulk_scraper.py urls.txt` or `python bulk_scraper.py <url1> <url2>`
  - Rate limited (3 seconds between requests)
  - All scraped recipes saved with `origin='bulk_scraped'`, `is_published=False`

- **import_climate_data.py** - Imports climate data into unified table:
  - `clear_climate_ingredients()` - Clear existing data for fresh import
  - `import_danish_db()` - Import from climate_data.xlsx (EN + DK names, nutrition)
  - `import_agribalyse()` - Import from Agribalyse Excel file (FR + EN names, CO2 only)
  - `get_stats()` - Show import statistics
  - `dry_run()` - Test parsing without database connection
  - Run: `python import_climate_data.py` (requires DATABASE_URL) or `python import_climate_data.py --dry-run`

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

1. **Input**: User enters recipe manually OR scrapes from URL (extracts title, servings, ingredients, og:image)
2. **Parse**: Preprocess informal units (handful, sprinkling, Danish spsk/tsk) → quantulum3 extracts quantities and units
3. **Match**: Hybrid matching (token-based + rapidfuzz) against cached `CLIMATE_NAMES` from Supabase; user confirms/corrects via autocomplete
4. **Calculate**: Convert to grams → lookup CO2-eq/kg and nutrition from `climate_ingredients` table → sum totals
5. **Save**: Store to PostgreSQL database with UUID, tags, source, original_line (for ML training), source_db (data provenance)

### Data Files (Source for Import Only)

These Excel files are used by `import_climate_data.py` to populate the Supabase `climate_ingredients` table. The web app reads exclusively from Supabase at runtime.

- **climate_data.xlsx** - Danish climate database with BOTH English (Name) and Danish (Navn) columns, plus nutrition data. ~540 ingredients.
- **AGRIBALYSE3.2_Tableur produits alimentaires_PublieAOUT25.xlsx** - French/EU Agribalyse database with French + English names, CO2 only (no nutrition). ~2,500 ingredients.

### Database Schema (PostgreSQL)

```sql
-- recipes table
CREATE TABLE recipes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    total_co2 REAL,
    servings REAL,
    co2_per_serving REAL,
    source TEXT,
    og_image_url TEXT,
    site_rating TEXT,
    original_ingredients TEXT,
    rating_label TEXT,
    rating_color TEXT,
    rating_emoji TEXT,
    nutrition_kcal REAL,
    nutrition_fat REAL,
    nutrition_carbs REAL,
    nutrition_protein REAL,
    origin TEXT DEFAULT 'user_created',  -- 'user_created', 'user_scraped', 'bulk_scraped'
    is_published BOOLEAN DEFAULT TRUE,   -- false for bulk-scraped until reviewed
    import_job_id TEXT,                  -- links to import_jobs for bulk imports
    language TEXT,                       -- 'en', 'da', 'fr', etc.
    domain TEXT,                         -- source website domain
    recipe_creator TEXT,                 -- user ID or 'admin' for bulk imports
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- recipe_ingredients table (with paper trail columns)
CREATE TABLE recipe_ingredients (
    id SERIAL PRIMARY KEY,
    recipe_id TEXT REFERENCES recipes(id) ON DELETE CASCADE,
    original_line TEXT,      -- Raw ingredient text for ML training
    item TEXT,               -- Matched ingredient name
    amount REAL,
    unit TEXT,
    grams REAL,
    co2 REAL,
    source_db TEXT           -- Which DB matched (danish/agribalyse/hestia)
);

-- recipe_tags table
CREATE TABLE recipe_tags (
    id SERIAL PRIMARY KEY,
    recipe_id TEXT REFERENCES recipes(id) ON DELETE CASCADE,
    tag TEXT
);

-- climate_ingredients table (Multi-Source Engine)
CREATE TABLE climate_ingredients (
    id SERIAL PRIMARY KEY,
    name_en TEXT,            -- English name
    name_dk TEXT,            -- Danish name
    name_fr TEXT,            -- French name (Agribalyse)
    co2_per_kg REAL NOT NULL,
    source_db TEXT NOT NULL, -- 'danish', 'agribalyse', 'hestia'
    source_id TEXT,          -- Original ID in source database
    confidence TEXT DEFAULT 'high',  -- 'highest', 'high', 'medium'
    category TEXT,
    subcategory TEXT,
    energy_kj REAL,
    fat_g REAL,
    carbs_g REAL,
    protein_g REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- import_jobs table (bulk scraping)
CREATE TABLE import_jobs (
    id TEXT PRIMARY KEY,
    status TEXT DEFAULT 'pending',       -- 'pending', 'processing', 'completed'
    total_urls INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- import_items table (individual URLs in a job)
CREATE TABLE import_items (
    id SERIAL PRIMARY KEY,
    job_id TEXT REFERENCES import_jobs(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    status TEXT DEFAULT 'pending',       -- 'pending', 'success', 'error'
    recipe_id TEXT REFERENCES recipes(id) ON DELETE SET NULL,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX idx_climate_name_en ON climate_ingredients(name_en);
CREATE INDEX idx_climate_name_dk ON climate_ingredients(name_dk);
CREATE INDEX idx_climate_name_fr ON climate_ingredients(name_fr);
CREATE INDEX idx_climate_source ON climate_ingredients(source_db);
CREATE INDEX idx_import_items_job ON import_items(job_id);
CREATE INDEX idx_import_items_status ON import_items(status);
```

### Config Files (config/)

- **units.json** - Unit conversions (g, kg, lb, oz, cup, handful, sprinkling, quart, etc.), ingredient weights (egg, onion, etc.), and unit name mappings (including "pound-mass" → "lb" for quantulum3 compatibility)
- **ingredient_aliases.json** - Maps common recipe terms to DB names (e.g., "ground beef" → "Beef, mince", "shallots" → "Onion, raw", herbs/spices → proper Agribalyse entries like "Oregano, dried", "Cumin, seed", "Basil, fresh")

## Dependencies

- flask - Web framework with Jinja2 templating
- quantulum3 - Parses quantities from natural language text (e.g., "200g beef")
- recipe_scrapers - Extracts recipe data from website URLs
- rapidfuzz - Fast fuzzy string matching for ingredient lookup
- psycopg2-binary - PostgreSQL database adapter
- gunicorn - Production WSGI server (for Render deployment)
- setuptools - Required for pkg_resources (quantulum3 dependency)
- pandas, openpyxl - Excel handling (only used by import_climate_data.py, not needed at runtime)

## Vision & Long-term Goals

**The Pivot: "Metacritic for Sustainable Cooking"**

Mealprint is pivoting from a simple recipe calculator to a high-volume, searchable index of recipes ranked by carbon impact. Think Metacritic, but for sustainable cooking.

- **Primary Goal:** Build the largest searchable database of carbon-rated recipes
- **Value Proposition:** Users discover low-carbon recipes from any source, with transparent CO2 ratings
- **Content Strategy:** Batch scrape recipes, auto-calculate CO2, human review for quality

### Multi-Source Climate Engine

The app now uses a unified `climate_ingredients` table with waterfall lookup across multiple databases:

| Priority | Database | Region | Confidence | Ingredients |
|----------|----------|--------|------------|-------------|
| 1st | Den Store Klimadatabase | Denmark | Highest | ~500 (with nutrition) |
| 2nd | Agribalyse (ADEME) | France/EU | High | ~2,500 (CO2 only) |
| 3rd | HESTIA/Oxford | Global | Medium | (Future) |

**Waterfall Logic:** Always prefer Danish (highest confidence), then Agribalyse, then HESTIA (future). Implemented via `confidence` column ordering in SQL queries.

### Paper Trail for ML Training

Each ingredient match now stores:
- `original_line` - The raw ingredient text from the recipe (e.g., "2 cups diced tomatoes")
- `source_db` - Which database the match came from (danish/agribalyse/hestia/legacy)

This enables future ML training to improve ingredient matching by learning from human corrections.

---

## Next Steps (Implementation Roadmap)

### Phase 2: Bulk Content Factory (COMPLETE)

**Goal:** Batch scrape recipes with manual review

Implemented:
- `ingredient_matcher.py` - Shared matching logic (parse_ingredients, calculate_ingredient, auto_match_ingredients)
- `bulk_scraper.py` - CLI tool for batch URL processing with rate limiting
- `import_jobs` / `import_items` tables - Track batch import progress
- Recipe columns: `origin`, `is_published`, `import_job_id`, `language`, `domain`, `recipe_creator`

**Origin values:**
- `user_created` - Manually entered via web UI
- `user_scraped` - User pasted URL, scraped via web UI
- `bulk_scraped` - Imported via bulk scraper (requires admin review)

### Phase 3: Admin Review UI (COMPLETE)

**Password Protection:** All `/admin/*` routes behind simple password (env var `ADMIN_PASSWORD`)

Implemented routes:
- `/admin/login` - Password login (session-based)
- `/admin/` - Dashboard with stats (published, pending, jobs)
- `/admin/import` - Submit URLs (textarea, one per line)
- `/admin/jobs` - List import jobs with status
- `/admin/jobs/<id>` - Job detail with URL list and "Run Job" button
- `/admin/jobs/<id>/run` - Start job processing (background thread)
- `/admin/review` - Queue of unpublished recipes needing review
- `/admin/review/<id>` - **Inline editing**: edit ingredients (amount/unit/name), tags, servings directly
- `/admin/review/<id>/save` - Save changes with CO2 recalculation, publish or save as draft
- `/admin/review/<id>/approve` - Quick publish without editing
- `/admin/review/<id>/reject` - Delete recipe

**Duplicate URL Handling:**
- Deduplicates URLs within submitted batch
- Skips URLs where a recipe with that source already exists
- Shows stats: "Added X URLs. Skipped Y duplicates, Z already scraped."

### Phase 4: Discovery Portal (NOT STARTED)

- `/discover` - Public searchable recipe index
- Filters: CO2 rating, tags, language, domain
- Pagination (fix N+1 query problem)
- "Inspiration cards" with image, title, CO2 badge, source link

### Future Enhancements
- **Google Sheets import** - One-click import from a configured Google Sheet (publish as CSV, store URL in env var, button in admin pulls URLs)
- **Automatic tagging** - Auto-generate tags during scraping:
  - Meal type: Pull from recipe metadata (breakfast, lunch, dinner, dessert, snack, etc.)
  - Nutrition: Based on calculated values (high protein, low carb, low calorie, etc.)
- **HESTIA database integration** - Global fallback for exotic ingredients
- **LLM fallback** - For < 40% confidence matches, call Claude API
- **Learn from corrections** - Log when users change matches, suggest new aliases
- **Percentile-based ratings** - "Low for a dessert" context-aware ratings
- **Danish language UI** - Full i18n with language switcher
- **Smart unit inference** - Intelligently determine default unit when missing (e.g., "2 carrots" → piece, "200 flour" → grams)

---

### Recently Completed
- **Phase 3: Admin Review UI** - Complete admin interface:
  - Password-protected admin area with session-based auth
  - Bulk URL import with background job processing
  - Inline recipe editing (ingredients, amounts, units, tags, servings)
  - CO2 recalculation on save
  - Duplicate URL detection (skips already-scraped URLs)
  - Save & Publish / Save as Draft workflow
- **Herb/spice aliases updated** - Now map to correct Agribalyse entries instead of defaulting to Basil/Parsley:
  - Dried herbs: oregano, thyme, rosemary, sage, marjoram, bay leaves
  - Fresh herbs: basil, parsley, dill, mint, cilantro, thyme, rosemary, sage, tarragon, chives
  - Spices: cumin, paprika, cinnamon, nutmeg, turmeric, cayenne, curry, cardamom, cloves, mustard
- **Phase 2: Bulk Content Factory** - Complete batch import pipeline:
  - `ingredient_matcher.py` - Shared parsing/matching logic for web app and bulk scraper
  - `bulk_scraper.py` - CLI tool: `python bulk_scraper.py urls.txt` (rate-limited, auto-match, saves unpublished)
  - `import_jobs` / `import_items` tables for tracking batch progress
  - Recipe metadata: `origin`, `is_published`, `import_job_id`, `language`, `domain`, `recipe_creator`
- **Supabase-only lookups** - Removed pandas/Excel dependency from runtime; all ingredient matching now uses cached `CLIMATE_NAMES` from Supabase. Simpler code (-115 lines), 3x more ingredients (2,957 vs ~540)
- **Multi-language support** - EN, DK, FR ingredient names all searchable through unified `climate_ingredients` table
- **Multi-Source Climate Engine** - Unified `climate_ingredients` table with 2,957 ingredients (499 Danish + 2,458 Agribalyse), waterfall lookup by confidence
- **Paper trail for ML training** - Each ingredient stores `original_line` (raw text) and `source_db` (data source) for future ML training
- **Import script** (`import_climate_data.py`) - Imports Danish DB and Agribalyse into unified table, supports `--dry-run` mode
- **Removed recipe instructions** - Copyright-safe: only store og_image_url and site_rating, not full instructions
- **Danish unit preprocessing** - spsk, tsk, stk, knivspids converted to standard units
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
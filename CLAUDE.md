# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mealprint is a Python/Flask application for calculating the carbon footprint (CO2 emissions) of recipes. It provides a web interface for users, an admin panel for bulk recipe import, and CLI tools for development.

**Vision:** "Metacritic for Sustainable Cooking" - a searchable index of recipes ranked by carbon impact, with transparent CO2 ratings and compliance-ready documentation.

## Deployment

**Production**: `mealprint.onrender.com`
- Gunicorn WSGI server, auto-deploys from `main` branch
- PostgreSQL on Supabase (free tier)

**Environment Variables**:
- `DATABASE_URL` - Supabase PostgreSQL connection string
- `MISTRAL_API_KEY` - AI ingredient matching (optional, admin-only)
- `ADMIN_PASSWORD` - Admin area password (defaults to 'admin' locally)

## Running Locally

```bash
# Web app (primary) - http://localhost:8080
python manual_app.py

# CLI tools
python meal_builder.py      # Interactive CLI
python auto_builder.py      # URL scraper
python bulk_scraper.py urls.txt  # Batch import
```

Requires `DATABASE_URL` pointing to Supabase.

## Architecture

### Core Modules

| File | Purpose |
|------|---------|
| `manual_app.py` | Flask web app - recipe input, calculation, history |
| `admin.py` | Admin blueprint - bulk import, review queue, job monitoring |
| `db.py` | Database layer - recipes, ingredients, climate data, import jobs |
| `ingredient_matcher.py` | Parsing & matching - quantulum3 + rapidfuzz + Mistral AI fallback |
| `recipe_manager.py` | Utilities - unit conversion, density lookup, rating calculation |
| `mistral_matcher.py` | AI matching - batch ingredient matching via Mistral API |
| `bulk_scraper.py` | CLI batch importer - scrapes URLs, auto-matches, saves as drafts |

### Key Features

**Ingredient Matching Pipeline:**
1. Parse with quantulum3 (extracts amounts/units)
2. Preprocess informal units (handful, spsk, knivspids)
3. Check aliases (`config/ingredient_aliases.json`)
4. Hybrid matching: token-based + rapidfuzz against 2,957 ingredients
5. AI fallback (Mistral) when confidence < 92%

**Density-Aware Conversion:**
- Volume units (cup, tbsp, ml) use ingredient-specific densities
- Config: `config/densities.json` (15 categories: flour, sugar, oil, etc.)
- Stored: `density_applied` column for transparency reports
- Example: 1 cup flour = 127g (not 240g)

**Multi-Source Climate Database:**
| Priority | Source | Ingredients | Data |
|----------|--------|-------------|------|
| 1st | ClimateDB (Danish) | ~500 | CO2 + nutrition |
| 2nd | Agribalyse (French) | ~2,500 | CO2 only |
| 3rd | HESTIA (future) | TBD | Global fallback |

**Admin Workflow:**
1. Submit URLs → creates import job
2. Run job → scrapes, auto-matches, saves as unpublished
3. Review queue → edit ingredients, approve/reject
4. AI re-match available for low-confidence matches

### Templates & Design

Jinja2 + Tailwind CSS (CDN). Key patterns:
- Container: `max-w-4xl mx-auto`
- Cards: `bg-white rounded-3xl shadow-sm border border-slate-200`
- CO2 colors: emerald (<1.0), amber (1.0-1.8), rose (>1.8 kg)
- Logo: Sour Gummy font (Medium 500, #4A7C59)
- JSON in forms: use single-quoted attributes `value='{{ data | tojson }}'`

### Database Schema

```sql
-- Core tables
recipes (id, name, total_co2, servings, co2_per_serving, source, og_image_url,
         rating_label/color/emoji, nutrition_*, origin, is_published, ...)

recipe_ingredients (recipe_id, original_line, item, amount, unit, grams, co2,
                   source_db, matched_by, density_applied)

recipe_tags (recipe_id, tag)

-- Climate data
climate_ingredients (name_en, name_dk, name_fr, co2_per_kg, source_db,
                    confidence, energy_kj, fat_g, carbs_g, protein_g)

-- Bulk import
import_jobs (id, status, total_urls, processed/success/error_count)
import_items (job_id, url, status, recipe_id, error_message)
```

### Config Files

| File | Purpose |
|------|---------|
| `config/units.json` | Unit conversions, ingredient weights, unit name mappings |
| `config/ingredient_aliases.json` | Common terms → DB names (herbs, spices, etc.) |
| `config/densities.json` | Density categories for volume→weight conversion |

### Migration Scripts

| Script | Purpose |
|--------|---------|
| `import_climate_data.py` | Import climate data from Excel files |
| `recalculate_recipes.py` | Recalculate all recipes (after density changes) |
| `backfill_density.py` | Populate density_applied for existing records |
| `migrate_source_names.py` | Rename source_db values |

## Dependencies

Core: flask, quantulum3, recipe_scrapers, rapidfuzz, psycopg2-binary, gunicorn
Import only: pandas, openpyxl

## Roadmap

### Phase 4: Discovery Portal (Next)
- `/discover` - Public searchable recipe index
- Filters: CO2 rating, tags, language, domain
- Pagination, "inspiration cards" with thumbnails

### Phase 5: Transparency Reports
- Per-recipe audit trail: ingredient breakdown, data sources, density applied
- Output: web view, PDF, JSON
- Use case: EU Green Claims compliance, B2B documentation

### Future Ideas
- HESTIA database integration (global ingredients)
- Google Sheets import for bulk URLs
- Auto-tagging (meal type, nutrition labels)
- Percentile-based ratings ("low for a dessert")
- Danish language UI

## Working Guidelines

- **MVP Thinking:** Build simplest version first. Break complex tasks into tiny steps.
- **Step-by-Step:** One task at a time. Explain logic before coding.
- **Coding Style:** Clear, descriptive code. No over-engineering.
- **Verification:** Provide a way to verify each change works.

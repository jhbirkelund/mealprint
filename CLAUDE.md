# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mealprint is a Python/Flask application for calculating the carbon footprint (CO2 emissions) of recipes. It provides a web interface for users, an admin panel for bulk recipe import, and CLI tools for development.

**Vision:** "Metacritic for Sustainable Cooking" - a searchable index of recipes ranked by carbon impact, with transparent CO2 ratings and compliance-ready documentation.

## Deployment

**Production**: `mealprint.onrender.com`
- Gunicorn WSGI server, auto-deploys from `main` branch
- PostgreSQL on Supabase (free tier)
- Config in `render.yaml` — start command: `gunicorn manual_app:app --timeout 120 --bind 0.0.0.0:10000`

**Environment Variables** (set in Render dashboard):
- `DATABASE_URL` - Supabase PostgreSQL connection string
- `MISTRAL_API_KEY` - AI ingredient matching (optional, admin-only)
- `ADMIN_PASSWORD` - Admin area password (defaults to 'admin' locally)
- `PYTHON_VERSION` - Set to `3.12.0` (pins Python version, avoids pkg_resources error on 3.13)

**Deployment troubleshooting**:
- `ModuleNotFoundError: No module named 'pkg_resources'` → Render cached an old venv. Use **"Clear build cache & deploy"** in the Render dashboard.
- Python version not changing → Check `PYTHON_VERSION` env var in Render dashboard, and clear build cache.

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
| `manual_app.py` | Flask web app - recipe input, calculation, history, resources |
| `admin.py` | Admin blueprint - bulk import, review queue, published list, job monitoring |
| `db.py` | Database layer - recipes, ingredients, climate data, import jobs |
| `ingredient_matcher.py` | Parsing & matching - ingredient-parser-nlp + rapidfuzz + Mistral AI fallback |
| `recipe_manager.py` | Utilities - unit conversion, density lookup, rating calculation |
| `mistral_matcher.py` | AI matching - batch ingredient matching via Mistral API |
| `bulk_scraper.py` | CLI batch importer - scrapes URLs, auto-matches, saves as drafts |

### Key Features

**Ingredient Matching Pipeline:**
1. Preprocess informal units (handful, dash, pinch, spsk, knivspids) - handles unitless "dash of X"
2. Parse with ingredient-parser-nlp (NLP/CRF model trained on 81k sentences — extracts amount, unit, clean name, strips prep notes)
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
| 1st | The Big Climate Database (Danish) | ~500 | CO2 + nutrition |
| 2nd | Agribalyse (French) | ~2,500 | CO2 only |
| 3rd | HESTIA (future) | TBD | Global fallback |

**Admin Workflow:**
1. Submit URLs → creates import job
2. Run job → scrapes, auto-matches, saves as unpublished
3. Review queue → edit ingredients, approve/reject
4. Published list → edit/rescrape existing recipes
5. AI re-match available for low-confidence matches

### Templates & Design

Jinja2 + Tailwind CSS (CDN). Key patterns:
- Container: `max-w-4xl mx-auto`
- Cards: `bg-white rounded-3xl shadow-sm border border-slate-200`
- CO2 colors: emerald (<1.0), amber (1.0-1.8), rose (>1.8 kg)
- Logo: Sour Gummy font (Medium 500, #4A7C59)
- Mobile: Hamburger menu (hidden md:flex pattern)
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
| `config/units.json` | Unit conversions (g, cup, fl oz, can), ingredient weights (egg, potato, chili), unit mappings |
| `config/ingredient_aliases.json` | Common terms → DB names (herbs, spices, fish sauce, cranberry, etc.) |
| `config/densities.json` | Density categories for volume→weight conversion |

### Migration Scripts

| Script | Purpose |
|--------|---------|
| `import_climate_data.py` | Import climate data from Excel files |
| `recalculate_recipes.py` | Recalculate all recipes (after density changes) |
| `backfill_density.py` | Populate density_applied for existing records |
| `migrate_source_names.py` | Rename source_db values |

## Dependencies

Core: flask, ingredient-parser-nlp, recipe_scrapers, rapidfuzz, psycopg2-binary, gunicorn
Import only: pandas, openpyxl

## Public Pages

| Route | Purpose |
|-------|---------|
| `/` | Explore - recipe list with search and tag filters |
| `/new` | Add Recipe - manual entry or URL scrape |
| `/recipe/<id>` | Recipe detail with CO2 breakdown |
| `/resources` | White papers index (methodology documentation) |
| `/resources/density` | Density conversion white paper |
| `/resources/matching` | Ingredient matching white paper (planned) |
| `/about-rating` | Carbon rating system explanation |

## Roadmap

### Phase 5: Transparency Reports

**Goal:** Public web report per recipe. Anyone with the link can verify and recreate the full CO2 calculation. Use case: EU Green Claims compliance, B2B documentation.

**URL:** `/recipe/<id>/report` (public, no login required)

**Prerequisite:** Block publishing if any ingredient is unmatched. Admin must resolve all ingredients before a recipe can go live.

**Page structure:**

1. **Header**
   - Recipe name + link to recipe page
   - Total CO2 (kg), servings, CO2 per serving
   - Report generated date

2. **Data Sources**
   - Static section listing the databases used in this report, with:
     - The Big Climate Database (https://thebigclimatedatabase.com/): description, date last imported into Mealprint
     - Agribalyse (https://agribalyse.ademe.fr): description, date last imported into Mealprint
   - Note: dates stored in a `db_metadata` table (key/value: `bigclimatedb_imported`, `agribalyse_imported`)

3. **Ingredient Audit Table**
   One row per ingredient. Columns:
   - **Original line** — raw text from recipe (e.g. "1 cup flour")
   - **Parsed amount + unit** — what the parser extracted (e.g. `1 cup`)
   - **Weight conversion** — how it became grams:
     - If density applied: `1 cup → 240 ml → 127g (density: 0.53 g/ml, category: flour)`
     - If direct weight unit: `250g` (no conversion needed)
     - If unit weight (e.g. egg): `2 eggs → 120g (unit weight: 60g/egg)`
   - **Matched ingredient** — name as it appears in the source DB
   - **Source DB** — The Big Climate Database or Agribalyse
   - **CO₂/kg** — the value pulled from the DB
   - **Calculated CO₂** — grams ÷ 1000 × CO₂/kg = result (shown as formula + result)

4. **Totals**
   - Sum of all ingredient CO₂ values = total CO₂
   - Total ÷ servings = CO₂ per serving
   - Matches the values shown on the recipe page

5. **Methodology note**
   - Brief explanation of the rating system, with link to `/about-rating`
   - Link to density white paper `/resources/density`

**Data already available in DB:**
- `recipe_ingredients`: original_line, item, amount, unit, grams, co2, source_db, matched_by, density_applied ✓
- `recipes`: total_co2, servings, co2_per_serving ✓
- Missing: `co2_per_kg` per ingredient (need to join with climate_ingredients at report render time)
- Missing: density details per ingredient (category, density value used) — need to store or re-derive
- Missing: `db_metadata` table for import dates — needs creating

### Phase 6: Security Hardening ✅ COMPLETE

**Critical (all done):**
- ✅ Passphrase protection on edit/delete routes (`require_edit_auth` decorator)
- ✅ CSRF tokens on all POST forms (`flask-wtf`)
- ✅ URL sanitization — `sanitize_url()` rejects non-http/https schemes
- ✅ Error handling — generic messages to users, details logged server-side
- ✅ `FLASK_DEBUG` default changed to `False`; `SECRET_KEY` confirmed in Render

**High priority (all done):**
- ✅ Rate limiting — 10/min on `/scrape`, 5/min on `/admin/login` (`flask-limiter`)
- ✅ Input validation — name max 200 chars, tags capped, servings/amounts positive only
- ✅ Security headers — X-Frame-Options, X-Content-Type-Options, HSTS via `after_request`
- ✅ Admin session hardening — HttpOnly, Secure, SameSite=Lax, 1hr idle timeout

### Phase 7: Compliance & Legal ✅ COMPLETE

- ✅ Privacy policy page (`/privacy`)
- ✅ Cookie notice banner in base.html (localStorage dismiss, session cookies only)
- ✅ Terms of service page (`/terms`)

**Needed before user accounts (deferred):**
- Data Processing Agreement with Supabase (their standard DPA, sign via Supabase dashboard)
- Right to deletion mechanism

**EU Green Claims (ongoing):**
- Keep transparency reports up to date — they serve as substantiation documents
- Establish a process for updating climate data sources when new versions release

### Phase 8: Pre-Launch Polish 🔄 IN PROGRESS

**Technical debt to clear:**
- ✅ Replace `quantulum3` with `ingredient-parser-nlp` — NLP/CRF model, much better accuracy on long ingredient descriptions; lazy-loaded for fast startup
- ✅ Fix unit mapping bugs — clove, head, stalk, slice, sprig now mapped; can weight fixed (always 400g); broccoli/cauliflower/cabbage/lettuce weights added
- ✅ Fix rescrape & AI re-match background jobs — stale cleanup now catches `pending/running/processing`; rescrape was crashing with KeyError (missing grams/co2 keys); now calls `calculate_ingredient()` and updates recipe totals
- ✅ Remove duplicate ingredient parsing — `get_processed_ingredients()` in `manual_app.py` was a diverged copy of `parse_ingredients()` in `ingredient_matcher.py`; deleted and replaced with shared function
- ✅ Fix Danish names in ingredient matching — `manual_app.py` was building its own `CLIMATE_NAMES` list including `name_dk`; now EN + FR only (same as `ingredient_matcher.py`)
- ✅ Ingredient matching accuracy pass — batch verification run surfaced ~20 bugs; fixed: word_match_score filter (>3 → >=3 to include short words like "red"/"soy"), first-name-only NLP token (no "or X or Y" pollution), explicit gram override for parenthetical weights ("1 cup (120g)"), MULTIPLIER guard for "2 x 400g cans", safe `getattr` for CompositeIngredientAmount, sprig as fixed-weight unit, CAN_WEIGHTS dict, substring false match ("tin" in "white"), hvidløg Danish alias, lasagna noodle piece weight, oil/wine/vinegar alias targets corrected, lemongrass, pumpkin seeds, dried_herbs density exclusions, cheese out of milk density

**Content & UX:**
- Build up recipe database to ~200+ quality published recipes across categories
- Add OG meta tags per recipe page (title, description, image) for link previews when shared
- ✅ Mobile UX review — sort button touch targets, ingredient name overflow, delete button padding
- 404 and 500 error pages that match the site design

**White paper: Ingredient Matching Logic** (`/resources/matching`)

Sits alongside the existing density white paper at `/resources/density`. Explains how Mealprint maps free-text recipe ingredients to the climate database, and why approximations are made where exact entries don't exist. All tables rendered live from the config files — no hardcoding.

Page structure:
1. **How the pipeline works** — step-by-step prose:
   - NLP parse (ingredient-parser-nlp extracts amount, unit, clean name — strips prep notes like "finely chopped")
   - Informal unit preprocessing (handful → 30g, knivspids → 0.5g, stk → 1 piece)
   - Alias lookup (longest-match substring against `config/ingredient_aliases.json`)
   - Hybrid matching: token word score + rapidfuzz WRatio against all DB names
   - Confidence threshold (word score ≥ 4 AND fuzzy ≥ 92%) — below triggers Mistral AI fallback

2. **Ingredient aliases table** — rendered live from `config/ingredient_aliases.json`
   Columns: Recipe term | Matched to in DB | Notes
   Grouped by category (dairy, oils, herbs, spices, pasta, etc.)
   Explains why approximations are used ("no Manchego in DB → nearest hard cheese")

3. **Piece weights table** — rendered live from `config/units.json` → `ingredient_weights`
   Columns: Ingredient | Weight per piece | Example
   Explains: when an ingredient has no volume unit (e.g. "2 eggs", "3 garlic cloves"), we look up a standard piece weight

4. **Density categories table** — rendered live from `config/densities.json`
   Columns: Category | Density (g/ml) | Applies to | Excludes
   Explains: volume measurements (1 cup flour) use ingredient-specific density, not water (1.0 g/ml)

5. **Limitations & methodology note**
   - Some ingredients have no close DB match — we use the nearest proxy (e.g. dried tarragon → oregano, dried)
   - Can weights default to 400g; tuna/sardine/anchovy use known sizes
   - Piece weights are population averages — actual ingredient size varies
   - Link to density white paper and `/about-rating`

**Recipe Verification Tool:**
- ✅ `verify_recipes.py` — terminal script, picks N random unverified published recipes, fetches source URLs, shows side-by-side stored vs. live ingredient comparison, marks all as `under_review`
- ✅ DB: `verification_status` column on `recipes` (`unverified` / `under_review` / `verified`)
- ✅ Admin: `/admin/verify` — lists `under_review` recipes for manual check and sign-off
- Run with: `DATABASE_URL="..." python3 verify_recipes.py --count 10`
- `ingredient_issues.md` — running list of matching/weight/density bugs found during verification; fix in bulk sessions
- ✅ `/admin/verify` — show all ingredients per recipe (not just discrepancies), so the full ingredient list is visible and can be signed off at a glance

**Monitoring:**
- Add basic error monitoring (Sentry free tier) so crashes surface without users reporting them
- Add Render health check endpoint (`/health` returning 200 OK)

### Phase 9: Soft Launch

- Internal go/no-go checklist: all Critical and High items in security tracker marked Fixed or Accepted
- Share with a small trusted group first (friends, sustainable food community)
- Set up a feedback channel (simple form or email)
- Monitor Render logs and Sentry for the first 48 hours
- Iterate on any blocking issues before broader promotion

### Future Ideas (Post-Launch)
- **User accounts** - Supabase Auth with OAuth (Google, GitHub). GDPR-compliant: minimal data stored, clear consent, right to deletion. Prerequisite for ratings, saved recipes, and personalisation. No email/password to keep it simple initially. Replaces passphrase edit/delete protection from Phase 6.
- **AI recipe description** - Short 2-3 sentence description of the dish, generated from scraped recipe data (title, ingredients, tags). Displayed on recipe page below the hero. Stored in DB to avoid re-generating.
- **User recipe ratings** - Internal star/thumbs rating for dish quality (separate from CO2 rating). Requires user accounts. Prompt for a rating after they've clicked through to the recipe site (inferred intent to cook). Aggregate into a Mealprint quality score displayed on the recipe page.
- **HESTIA database integration** (global ingredients)
- **Google Sheets import** for bulk URLs
- **Auto-tagging** (meal type, nutrition labels)
- **Percentile-based ratings** ("low for a dessert")
- **Danish language UI**

## Working Guidelines

- **MVP Thinking:** Build simplest version first. Break complex tasks into tiny steps.
- **Step-by-Step:** One task at a time. Explain logic before coding.
- **Coding Style:** Clear, descriptive code. No over-engineering.
- **Verification:** Provide a way to verify each change works.

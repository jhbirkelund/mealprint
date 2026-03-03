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
| `ingredient_matcher.py` | Parsing & matching - quantulum3 + rapidfuzz + Mistral AI fallback |
| `recipe_manager.py` | Utilities - unit conversion, density lookup, rating calculation |
| `mistral_matcher.py` | AI matching - batch ingredient matching via Mistral API |
| `bulk_scraper.py` | CLI batch importer - scrapes URLs, auto-matches, saves as drafts |

### Key Features

**Ingredient Matching Pipeline:**
1. Parse with quantulum3 (extracts amounts/units)
2. Preprocess informal units (handful, dash, pinch, spsk, knivspids) - handles unitless "dash of X"
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

Core: flask, quantulum3, recipe_scrapers, rapidfuzz, psycopg2-binary, gunicorn
Import only: pandas, openpyxl

## Public Pages

| Route | Purpose |
|-------|---------|
| `/` | Explore - recipe list with search and tag filters |
| `/new` | Add Recipe - manual entry or URL scrape |
| `/recipe/<id>` | Recipe detail with CO2 breakdown |
| `/resources` | White papers index (methodology documentation) |
| `/resources/density` | Density conversion white paper |
| `/about-rating` | Carbon rating system explanation |

## Roadmap

### Phase 4: Discovery Portal (Next)
- `/discover` - Public searchable recipe index
- Filters: CO2 rating, tags, language, domain
- Pagination, "inspiration cards" with thumbnails

### Fix: Replace quantulum3 parser
- `quantulum3` is unmaintained and breaks on new Python/setuptools versions (currently pinned to `setuptools<71` as workaround)
- Used in exactly two files (`ingredient_matcher.py`, `manual_app.py`) for one purpose: extract number + unit + surface from ingredient strings
- Replace with a custom regex parser built against the known unit list in `config/units.json` (~20-30 lines, zero dependencies)

### Fix: Rescrape & AI Re-match Timeouts
- Rescrape and AI re-match in admin frequently time out — they run synchronously during the HTTP request (scraping + Mistral API calls can take 10-30s)
- Fix: run them as background jobs (same pattern as bulk import — queue a job, poll for completion)
- Affects: "Rescrape" and "AI Re-match" buttons in admin review queue and published list

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
     - ClimateDB: description, link to climatedb.dk, date last imported into Mealprint
     - Agribalyse: description, link to agribalyse.fr, date last imported into Mealprint
   - Note: dates stored in a `db_metadata` table (key/value: `climatedb_imported`, `agribalyse_imported`)

3. **Ingredient Audit Table**
   One row per ingredient. Columns:
   - **Original line** — raw text from recipe (e.g. "1 cup flour")
   - **Parsed amount + unit** — what the parser extracted (e.g. `1 cup`)
   - **Weight conversion** — how it became grams:
     - If density applied: `1 cup → 240 ml → 127g (density: 0.53 g/ml, category: flour)`
     - If direct weight unit: `250g` (no conversion needed)
     - If unit weight (e.g. egg): `2 eggs → 120g (unit weight: 60g/egg)`
   - **Matched ingredient** — name as it appears in the source DB
   - **Source DB** — ClimateDB or Agribalyse
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

### Phase 7: Compliance & Legal *(prerequisite for external users)*

**Required before launch:**
- Privacy policy page (`/privacy`) — what data is collected, why, how long kept, who processes it (Supabase)
- Cookie disclosure — session cookies only, no tracking. Add minimal notice to footer or banner
- Terms of service page (`/terms`) — acceptable use, no liability for CO2 accuracy, content ownership

**Needed before user accounts:**
- Data retention policy (defined in privacy policy)
- Data Processing Agreement with Supabase (their standard DPA, sign via Supabase dashboard)
- Right to deletion mechanism

**EU Green Claims (ongoing):**
- Keep transparency reports up to date — they serve as substantiation documents
- Establish a process for updating climate data sources when new versions release

### Phase 8: Pre-Launch Polish

**Technical debt to clear:**
- Replace `quantulum3` with custom regex parser — removes fragile dependency, fixes potential parse hangs (see Fix note above)
- Fix rescrape & AI re-match timeouts — move to background jobs (see Fix note above)

**Content & UX:**
- Build up recipe database to ~200+ quality published recipes across categories
- Add OG meta tags per recipe page (title, description, image) for link previews when shared
- Review mobile UX end-to-end — the primary use case is looking up a recipe on your phone
- 404 and 500 error pages that match the site design

**Recipe Verification Tool:**
- Terminal script (`verify_recipes.py`) — picks 10 random `unverified` published recipes, fetches each original URL, uses Claude (Anthropic API) to compare against stored data
- Terminal output: summary only — "Checked 10 — 7 verified, 3 flagged for review"
- DB: add `verification_status` column to `recipes` (values: `unverified` / `under_review` / `verified`, default `unverified`)
- Admin: `/admin/review` list filtered to `under_review` recipes — admin manually checks, fixes, and marks as `verified`
- New dependency: `anthropic` Python package + `ANTHROPIC_API_KEY` env var
- Long-term path: shifts human review from all recipes → flagged-only

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

import os
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor

def get_connection():
    """Get a database connection using DATABASE_URL environment variable."""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise Exception("DATABASE_URL environment variable not set")
    return psycopg2.connect(database_url)

def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    cur = conn.cursor()

    # Create recipes table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recipes (
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Migration: Add new columns if they don't exist (for existing databases)
    # Use IF NOT EXISTS pattern to avoid transaction failures
    cur.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='og_image_url') THEN
                ALTER TABLE recipes ADD COLUMN og_image_url TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='site_rating') THEN
                ALTER TABLE recipes ADD COLUMN site_rating TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='origin') THEN
                ALTER TABLE recipes ADD COLUMN origin TEXT DEFAULT 'user_created';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='is_published') THEN
                ALTER TABLE recipes ADD COLUMN is_published BOOLEAN DEFAULT TRUE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='import_job_id') THEN
                ALTER TABLE recipes ADD COLUMN import_job_id TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='language') THEN
                ALTER TABLE recipes ADD COLUMN language TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='domain') THEN
                ALTER TABLE recipes ADD COLUMN domain TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='recipe_creator') THEN
                ALTER TABLE recipes ADD COLUMN recipe_creator TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipes' AND column_name='verification_status') THEN
                ALTER TABLE recipes ADD COLUMN verification_status TEXT DEFAULT 'unverified';
            END IF;
        END $$;
    ''')

    # Create recipe_ingredients table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id SERIAL PRIMARY KEY,
            recipe_id TEXT REFERENCES recipes(id) ON DELETE CASCADE,
            original_line TEXT,
            item TEXT,
            amount REAL,
            unit TEXT,
            grams REAL,
            co2 REAL,
            source_db TEXT
        )
    ''')

    # Migration: Add new columns if they don't exist
    cur.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipe_ingredients' AND column_name='original_line') THEN
                ALTER TABLE recipe_ingredients ADD COLUMN original_line TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipe_ingredients' AND column_name='source_db') THEN
                ALTER TABLE recipe_ingredients ADD COLUMN source_db TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipe_ingredients' AND column_name='matched_by') THEN
                ALTER TABLE recipe_ingredients ADD COLUMN matched_by TEXT DEFAULT 'fuzzy';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='recipe_ingredients' AND column_name='density_applied') THEN
                ALTER TABLE recipe_ingredients ADD COLUMN density_applied REAL;
            END IF;
        END $$;
    ''')

    # Create recipe_tags table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recipe_tags (
            id SERIAL PRIMARY KEY,
            recipe_id TEXT REFERENCES recipes(id) ON DELETE CASCADE,
            tag TEXT
        )
    ''')

    # Create unified climate_ingredients table (Multi-Source Engine)
    # Sources: danish (highest), agribalyse (high), hestia (medium)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS climate_ingredients (
            id SERIAL PRIMARY KEY,
            name_en TEXT,
            name_dk TEXT,
            name_fr TEXT,
            co2_per_kg REAL NOT NULL,
            source_db TEXT NOT NULL,
            source_id TEXT,
            confidence TEXT DEFAULT 'high',
            category TEXT,
            subcategory TEXT,
            energy_kj REAL,
            fat_g REAL,
            carbs_g REAL,
            protein_g REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create indexes for fast ingredient lookups
    cur.execute('CREATE INDEX IF NOT EXISTS idx_climate_name_en ON climate_ingredients(name_en)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_climate_name_dk ON climate_ingredients(name_dk)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_climate_name_fr ON climate_ingredients(name_fr)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_climate_source ON climate_ingredients(source_db)')

    # Create import_jobs table for batch scraping and single-recipe background jobs
    cur.execute('''
        CREATE TABLE IF NOT EXISTS import_jobs (
            id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'pending',
            total_urls INTEGER DEFAULT 0,
            processed_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')

    # Add columns for single-recipe jobs (idempotent — safe to run on every startup)
    cur.execute("ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS job_type TEXT DEFAULT 'bulk_import'")
    cur.execute("ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS recipe_id TEXT")
    cur.execute("ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS result_message TEXT")

    # Create import_items table for individual URLs in a job
    cur.execute('''
        CREATE TABLE IF NOT EXISTS import_items (
            id SERIAL PRIMARY KEY,
            job_id TEXT REFERENCES import_jobs(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            recipe_id TEXT REFERENCES recipes(id) ON DELETE SET NULL,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP
        )
    ''')

    # Create indexes for import tables
    cur.execute('CREATE INDEX IF NOT EXISTS idx_import_items_job ON import_items(job_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_import_items_status ON import_items(status)')

    # Create security_tracker table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS security_tracker (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'open',
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Seed initial items if table is empty
    cur.execute('SELECT COUNT(*) FROM security_tracker')
    count = cur.fetchone()[0]
    if count == 0:
        items = [
            # ── Security: Critical ──────────────────────────────────────────
            ('security', 'critical', 'No auth on recipe delete',
             '/delete/<id> is a plain GET route with no authentication. Any visitor can delete any recipe.',
             'open', None),
            ('security', 'critical', 'No auth on recipe edit/update',
             '/edit/<id> and /update/<id> have no authentication. Anyone can modify any recipe.',
             'open', None),
            ('security', 'critical', 'No CSRF protection on any form',
             'No CSRF tokens on any POST form. Attacker can trick logged-in users into triggering delete, edit, or publish actions.',
             'open', None),
            ('security', 'critical', 'Weak admin authentication',
             'Admin password is plaintext comparison with default value "admin". No rate limiting, no brute-force protection.',
             'open', None),
            # ── Security: High ──────────────────────────────────────────────
            ('security', 'high', 'SECRET_KEY defaults to known dev value',
             'If SECRET_KEY env var is not set in Render, sessions can be forged. Default key is publicly documented.',
             'open', None),
            ('security', 'high', 'XSS via recipe source URL in href',
             'recipe.source is used directly in <a href="{{ recipe.source }}"> with no validation. javascript: URLs execute on click.',
             'open', None),
            ('security', 'high', 'XSS via og_image_url in img src',
             'og_image_url passed through form and stored without validation. Used as <img src="..."> — allows tracking pixels and bad URLs.',
             'open', None),
            ('security', 'high', 'XSS via recipe tags',
             'Tags are stored and rendered without sanitization. Attacker could inject HTML via a tag.',
             'open', None),
            ('security', 'high', 'SSRF via /scrape route',
             '/scrape accepts any URL including internal addresses (localhost, 127.0.0.1, cloud metadata endpoints). No domain validation.',
             'open', None),
            ('security', 'high', 'Stack traces exposed to users',
             'Error handlers return str(e) directly to the client. Can leak DB structure, file paths, or key names.',
             'open', None),
            ('security', 'high', 'No rate limiting anywhere',
             'No rate limiting on /scrape, /calculate, /admin/login, or any other route. Open to spam, brute force, and DoS.',
             'open', None),
            ('security', 'high', 'FLASK_DEBUG defaults to True',
             'manual_app.py defaults FLASK_DEBUG to True if env var not set. Exposes interactive debugger in production.',
             'open', None),
            # ── Security: Medium ─────────────────────────────────────────────
            ('security', 'medium', 'No input validation on recipe fields',
             'Recipe name, servings, amounts, and tags have no length limits, range checks, or character validation.',
             'open', None),
            ('security', 'medium', 'Admin session never expires',
             'Admin session has no idle timeout and no HttpOnly/Secure/SameSite cookie flags.',
             'open', None),
            ('security', 'medium', 'No audit logging',
             'No record of who created, edited, deleted, published, or rejected recipes. Cannot investigate incidents.',
             'open', None),
            ('security', 'medium', 'DB connection leaks on exceptions',
             'db.py does not use try/finally or context managers for connections. Exceptions leave connections open.',
             'open', None),
            # ── Security: Low ────────────────────────────────────────────────
            ('security', 'low', 'Missing security headers',
             'No X-Frame-Options, X-Content-Type-Options, Strict-Transport-Security, or Content-Security-Policy headers.',
             'open', None),
            ('security', 'low', 'Quantulum3 parser unmaintained',
             'quantulum3 is unmaintained and known to hang on edge-case regex inputs. Roadmap item to replace with custom parser.',
             'open', None),
            # ── Compliance: GDPR ─────────────────────────────────────────────
            ('compliance', 'high', 'No privacy policy',
             'No privacy policy page. Required under GDPR if collecting or processing any personal data (e.g. IP logs, future user accounts).',
             'open', None),
            ('compliance', 'high', 'No cookie consent banner',
             'Session cookies set without user consent or disclosure. Required under ePrivacy Directive (EU Cookie Law).',
             'open', None),
            ('compliance', 'medium', 'No data retention policy',
             'No defined policy for how long user-submitted recipes are stored. Required for GDPR compliance.',
             'open', None),
            ('compliance', 'medium', 'No data processing agreement with Supabase',
             'Supabase processes data on behalf of Mealprint. A DPA should be in place before handling personal data.',
             'open', None),
            ('compliance', 'medium', 'No right to deletion mechanism',
             'If user accounts are added, users must be able to request deletion of their data. No mechanism exists yet.',
             'open', None),
            ('compliance', 'low', 'No terms of service',
             'No ToS defining acceptable use, liability, or content ownership.',
             'open', None),
            ('compliance', 'low', 'No accessibility statement (WCAG)',
             'No WCAG 2.1 compliance review or accessibility statement. Required for EU public sector, good practice elsewhere.',
             'open', None),
            # ── Compliance: EU Green Claims ────────────────────────────────────
            ('compliance', 'medium', 'EU Green Claims: methodology substantiation',
             'EU Green Claims Directive requires documented, verifiable methodology for environmental claims. Transparency reports are a start — need third-party review.',
             'open', None),
            ('compliance', 'medium', 'EU Green Claims: data source currency',
             'CO2 data must be kept up to date. Need a process for reviewing and updating ClimateDB and Agribalyse imports.',
             'open', None),
            ('compliance', 'low', 'EU Green Claims: third-party verification',
             'Claims may require independent verification to meet the full requirements of the EU Green Claims Directive.',
             'open', None),
        ]
        cur.executemany('''
            INSERT INTO security_tracker (category, severity, title, description, status, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', items)

    conn.commit()
    cur.close()
    conn.close()

def save_recipe_to_db(recipe_name, ingredients, total_co2, servings, nutrition=None, tags=None, source=None, og_image_url=None, site_rating=None, original_ingredients=None, rating=None, origin='user_created', is_published=True, import_job_id=None, language=None, domain=None, recipe_creator=None):
    """Save a recipe to the database."""
    recipe_id = str(uuid.uuid4())
    co2_per_serving = round(total_co2 / servings, 3) if servings > 0 else 0

    conn = get_connection()
    cur = conn.cursor()

    # Insert recipe
    cur.execute('''
        INSERT INTO recipes (id, name, total_co2, servings, co2_per_serving, source, og_image_url, site_rating, original_ingredients,
                            rating_label, rating_color, rating_emoji,
                            nutrition_kcal, nutrition_fat, nutrition_carbs, nutrition_protein,
                            origin, is_published, import_job_id, language, domain, recipe_creator)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        recipe_id,
        recipe_name,
        round(total_co2, 3),
        servings,
        co2_per_serving,
        source or '',
        og_image_url or '',
        site_rating or '',
        original_ingredients or '',
        rating['label'] if rating else '',
        rating['color'] if rating else '',
        rating['emoji'] if rating else '',
        nutrition.get('kcal', 0) if nutrition else 0,
        nutrition.get('fat', 0) if nutrition else 0,
        nutrition.get('carbs', 0) if nutrition else 0,
        nutrition.get('protein', 0) if nutrition else 0,
        origin,
        is_published,
        import_job_id,
        language,
        domain,
        recipe_creator
    ))

    # Insert ingredients
    for ing in ingredients:
        cur.execute('''
            INSERT INTO recipe_ingredients (recipe_id, original_line, item, amount, unit, grams, co2, source_db, matched_by, density_applied)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            recipe_id,
            ing.get('original_line', ''),
            ing.get('item', ''),
            ing.get('amount', 0),
            ing.get('unit', 'g'),
            ing.get('grams', 0),
            ing.get('co2', 0),
            ing.get('source_db', ''),
            ing.get('matched_by', 'fuzzy'),
            ing.get('density_applied')
        ))

    # Insert tags
    if tags:
        for tag in tags:
            cur.execute('''
                INSERT INTO recipe_tags (recipe_id, tag)
                VALUES (%s, %s)
            ''', (recipe_id, tag))

    conn.commit()
    cur.close()
    conn.close()

    return recipe_id

def get_published_recipes_for_explore():
    """Get all published recipes for the explore page in a single query.

    Only fetches fields needed for recipe cards — does NOT load ingredients.
    Uses a JOIN for tags so the whole page costs exactly 1 DB query.
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute('''
        SELECT
            r.id, r.name, r.co2_per_serving,
            r.rating_label, r.rating_color, r.rating_emoji,
            r.og_image_url, r.site_rating, r.created_at,
            COALESCE(
                array_agg(rt.tag ORDER BY rt.tag) FILTER (WHERE rt.tag IS NOT NULL),
                '{}'
            ) AS tags
        FROM recipes r
        LEFT JOIN recipe_tags rt ON r.id = rt.recipe_id
        WHERE r.is_published = TRUE
        GROUP BY r.id, r.name, r.co2_per_serving, r.rating_label, r.rating_color,
                 r.rating_emoji, r.og_image_url, r.site_rating, r.created_at
        ORDER BY r.created_at DESC
    ''')

    rows = cur.fetchall()
    cur.close()
    conn.close()

    results = []
    for r in rows:
        results.append({
            'id': r['id'],
            'name': r['name'],
            'co2_per_serving': r['co2_per_serving'] or 0,
            'og_image_url': r['og_image_url'],
            'site_rating': r['site_rating'],
            'created_at': r['created_at'],
            'tags': list(r['tags']) if r['tags'] else [],
            'rating': {
                'label': r['rating_label'],
                'color': r['rating_color'],
                'emoji': r['rating_emoji'],
            } if r['rating_label'] else None
        })

    return results


def get_all_recipes():
    """Get all recipes from the database."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute('SELECT * FROM recipes ORDER BY created_at DESC')
    recipes = cur.fetchall()

    # Convert to list of dicts with nested structures (matching JSON format)
    result = []
    for r in recipes:
        # Get ingredients for this recipe (including original_line, source_db, and matched_by for paper trail)
        cur.execute('SELECT original_line, item, amount, unit, grams, co2, source_db, matched_by, density_applied FROM recipe_ingredients WHERE recipe_id = %s', (r['id'],))
        ingredients = [dict(ing) for ing in cur.fetchall()]

        # Get tags for this recipe
        cur.execute('SELECT tag FROM recipe_tags WHERE recipe_id = %s', (r['id'],))
        tags = [row['tag'] for row in cur.fetchall()]

        result.append({
            'id': r['id'],
            'name': r['name'],
            'total_co2': r['total_co2'],
            'servings': r['servings'],
            'co2_per_serving': r['co2_per_serving'],
            'source': r['source'],
            'og_image_url': r.get('og_image_url', ''),
            'site_rating': r.get('site_rating', ''),
            'original_ingredients': r['original_ingredients'],
            'rating': {
                'label': r['rating_label'],
                'color': r['rating_color'],
                'emoji': r['rating_emoji']
            },
            'tags': tags,
            'ingredients': ingredients,
            'metadata': {
                'nutrition': {
                    'kcal': r['nutrition_kcal'],
                    'fat': r['nutrition_fat'],
                    'carbs': r['nutrition_carbs'],
                    'protein': r['nutrition_protein']
                }
            },
            'origin': r.get('origin', 'user_created'),
            'is_published': r.get('is_published', True),
            'import_job_id': r.get('import_job_id'),
            'language': r.get('language'),
            'domain': r.get('domain'),
            'recipe_creator': r.get('recipe_creator')
        })

    cur.close()
    conn.close()
    return result

def get_recipe_by_id(recipe_id):
    """Get a single recipe by ID."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute('SELECT * FROM recipes WHERE id = %s', (recipe_id,))
    r = cur.fetchone()

    if not r:
        cur.close()
        conn.close()
        return None

    # Get ingredients (including original_line, source_db, and matched_by for paper trail)
    cur.execute('SELECT original_line, item, amount, unit, grams, co2, source_db, matched_by, density_applied FROM recipe_ingredients WHERE recipe_id = %s', (recipe_id,))
    ingredients = [dict(ing) for ing in cur.fetchall()]

    # Get tags
    cur.execute('SELECT tag FROM recipe_tags WHERE recipe_id = %s', (recipe_id,))
    tags = [row['tag'] for row in cur.fetchall()]

    cur.close()
    conn.close()

    return {
        'id': r['id'],
        'name': r['name'],
        'total_co2': r['total_co2'],
        'servings': r['servings'],
        'co2_per_serving': r['co2_per_serving'],
        'source': r['source'],
        'og_image_url': r.get('og_image_url', ''),
        'site_rating': r.get('site_rating', ''),
        'original_ingredients': r['original_ingredients'],
        'rating': {
            'label': r['rating_label'],
            'color': r['rating_color'],
            'emoji': r['rating_emoji']
        },
        'tags': tags,
        'ingredients': ingredients,
        'metadata': {
            'nutrition': {
                'kcal': r['nutrition_kcal'],
                'fat': r['nutrition_fat'],
                'carbs': r['nutrition_carbs'],
                'protein': r['nutrition_protein']
            }
        },
        'origin': r.get('origin', 'user_created'),
        'is_published': r.get('is_published', True),
        'import_job_id': r.get('import_job_id'),
        'language': r.get('language'),
        'domain': r.get('domain'),
        'recipe_creator': r.get('recipe_creator')
    }

def update_recipe_in_db(recipe_id, recipe_name, ingredients, total_co2, servings, nutrition=None, tags=None, source=None, og_image_url=None, site_rating=None, original_ingredients=None, rating=None):
    """Update an existing recipe in the database."""
    co2_per_serving = round(total_co2 / servings, 3) if servings > 0 else 0

    conn = get_connection()
    cur = conn.cursor()

    # Update recipe
    cur.execute('''
        UPDATE recipes SET
            name = %s,
            total_co2 = %s,
            servings = %s,
            co2_per_serving = %s,
            source = %s,
            og_image_url = %s,
            site_rating = %s,
            original_ingredients = %s,
            rating_label = %s,
            rating_color = %s,
            rating_emoji = %s,
            nutrition_kcal = %s,
            nutrition_fat = %s,
            nutrition_carbs = %s,
            nutrition_protein = %s
        WHERE id = %s
    ''', (
        recipe_name,
        round(total_co2, 3),
        servings,
        co2_per_serving,
        source or '',
        og_image_url or '',
        site_rating or '',
        original_ingredients or '',
        rating['label'] if rating else '',
        rating['color'] if rating else '',
        rating['emoji'] if rating else '',
        nutrition.get('kcal', 0) if nutrition else 0,
        nutrition.get('fat', 0) if nutrition else 0,
        nutrition.get('carbs', 0) if nutrition else 0,
        nutrition.get('protein', 0) if nutrition else 0,
        recipe_id
    ))

    # Delete old ingredients and tags
    cur.execute('DELETE FROM recipe_ingredients WHERE recipe_id = %s', (recipe_id,))
    cur.execute('DELETE FROM recipe_tags WHERE recipe_id = %s', (recipe_id,))

    # Insert new ingredients
    for ing in ingredients:
        cur.execute('''
            INSERT INTO recipe_ingredients (recipe_id, original_line, item, amount, unit, grams, co2, source_db, matched_by, density_applied)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            recipe_id,
            ing.get('original_line', ''),
            ing.get('item', ''),
            ing.get('amount', 0),
            ing.get('unit', 'g'),
            ing.get('grams', 0),
            ing.get('co2', 0),
            ing.get('source_db', ''),
            ing.get('matched_by', 'fuzzy'),
            ing.get('density_applied')
        ))

    # Insert new tags
    if tags:
        for tag in tags:
            cur.execute('''
                INSERT INTO recipe_tags (recipe_id, tag)
                VALUES (%s, %s)
            ''', (recipe_id, tag))

    conn.commit()
    cur.close()
    conn.close()

def delete_recipe_from_db(recipe_id):
    """Delete a recipe from the database."""
    conn = get_connection()
    cur = conn.cursor()

    # Due to ON DELETE CASCADE, ingredients and tags will be deleted automatically
    cur.execute('DELETE FROM recipes WHERE id = %s', (recipe_id,))

    conn.commit()
    cur.close()
    conn.close()


# =============================================================================
# Climate Ingredients - Multi-Source Lookup Functions
# =============================================================================

def get_all_climate_ingredients():
    """Get all ingredient names for autocomplete dropdown.

    Returns all language variants (EN, DK, FR) for each ingredient to support
    multi-language searching and autocomplete.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Get all ingredients with all name variants
    cur.execute('''
        SELECT
            id,
            name_en,
            name_dk,
            name_fr,
            co2_per_kg,
            source_db,
            confidence
        FROM climate_ingredients
        WHERE name_en IS NOT NULL OR name_dk IS NOT NULL OR name_fr IS NOT NULL
        ORDER BY COALESCE(name_en, name_dk, name_fr)
    ''')
    results = cur.fetchall()

    cur.close()
    conn.close()

    # Build list with all searchable names pointing to same ingredient data
    ingredients = []
    for r in results:
        ing_id, name_en, name_dk, name_fr, co2, source, confidence = r
        # Primary display name (what's shown in dropdown)
        display_name = name_en or name_dk or name_fr
        ingredients.append({
            'id': ing_id,
            'name': display_name,  # For backwards compatibility
            'name_en': name_en,
            'name_dk': name_dk,
            'name_fr': name_fr,
            'co2_per_kg': co2,
            'source': source,
            'confidence': confidence
        })

    return ingredients


def search_climate_ingredients(search_term, limit=20):
    """
    Search climate_ingredients with waterfall priority:
    1. Danish DB (highest confidence)
    2. Agribalyse (high confidence)

    Returns matches sorted by: confidence desc, relevance
    """
    conn = get_connection()
    cur = conn.cursor()

    search_pattern = f'%{search_term}%'

    # Search across all name fields, prioritize by source confidence
    cur.execute('''
        SELECT
            id,
            COALESCE(name_en, name_dk, name_fr) as display_name,
            name_en,
            name_dk,
            name_fr,
            co2_per_kg,
            source_db,
            confidence,
            category,
            energy_kj,
            fat_g,
            carbs_g,
            protein_g
        FROM climate_ingredients
        WHERE
            name_en ILIKE %s OR
            name_dk ILIKE %s OR
            name_fr ILIKE %s
        ORDER BY
            CASE confidence
                WHEN 'highest' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                ELSE 4
            END,
            CASE
                WHEN name_en ILIKE %s THEN 0
                WHEN name_dk ILIKE %s THEN 0
                ELSE 1
            END,
            LENGTH(COALESCE(name_en, name_dk, name_fr))
        LIMIT %s
    ''', (search_pattern, search_pattern, search_pattern,
          search_term + '%', search_term + '%', limit))

    results = cur.fetchall()
    cur.close()
    conn.close()

    return [{
        'id': r[0],
        'name': r[1],
        'name_en': r[2],
        'name_dk': r[3],
        'name_fr': r[4],
        'co2_per_kg': r[5],
        'source_db': r[6],
        'confidence': r[7],
        'category': r[8],
        'energy_kj': r[9],
        'fat_g': r[10],
        'carbs_g': r[11],
        'protein_g': r[12]
    } for r in results]


def get_ingredient_by_name(name):
    """
    Get a single ingredient by exact name match.
    Matches against display name (COALESCE) or any individual name column.
    Uses waterfall: Danish first, then Agribalyse.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Try exact match against display name or any column, prioritize by confidence
    cur.execute('''
        SELECT
            id,
            COALESCE(name_en, name_dk, name_fr) as display_name,
            name_en,
            name_dk,
            name_fr,
            co2_per_kg,
            source_db,
            confidence,
            category,
            energy_kj,
            fat_g,
            carbs_g,
            protein_g
        FROM climate_ingredients
        WHERE
            COALESCE(name_en, name_dk, name_fr) = %s OR
            name_en = %s OR
            name_dk = %s OR
            name_fr = %s
        ORDER BY
            CASE confidence
                WHEN 'highest' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                ELSE 4
            END
        LIMIT 1
    ''', (name, name, name, name))

    result = cur.fetchone()
    cur.close()
    conn.close()

    if not result:
        return None

    return {
        'id': result[0],
        'name': result[1],
        'name_en': result[2],
        'name_dk': result[3],
        'name_fr': result[4],
        'co2_per_kg': result[5],
        'source_db': result[6],
        'confidence': result[7],
        'category': result[8],
        'energy_kj': result[9],
        'fat_g': result[10],
        'carbs_g': result[11],
        'protein_g': result[12]
    }


# =============================================================================
# Import Jobs - Bulk Scraping Management
# =============================================================================

def recipe_exists_by_source(source_url):
    """Check if a recipe with this source URL already exists."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT id FROM recipes WHERE source = %s LIMIT 1', (source_url,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result is not None


def create_import_job(urls):
    """Create a new import job with a list of URLs to process.

    Deduplicates URLs and skips any that already exist as recipes.
    Returns (job_id, stats) where stats contains counts of added/skipped URLs.
    """
    # Deduplicate URLs (preserve order)
    seen = set()
    unique_urls = []
    for url in urls:
        url = url.strip()
        if url and url not in seen:
            seen.add(url)
            unique_urls.append(url)

    # Filter out URLs that already exist as recipes
    new_urls = []
    skipped_existing = 0
    for url in unique_urls:
        if recipe_exists_by_source(url):
            skipped_existing += 1
        else:
            new_urls.append(url)

    # If no new URLs, don't create a job
    if not new_urls:
        return None, {
            'total_submitted': len(urls),
            'duplicates_in_list': len(urls) - len(unique_urls),
            'already_scraped': skipped_existing,
            'added': 0
        }

    job_id = str(uuid.uuid4())

    conn = get_connection()
    cur = conn.cursor()

    # Create the job
    cur.execute('''
        INSERT INTO import_jobs (id, status, total_urls)
        VALUES (%s, 'pending', %s)
    ''', (job_id, len(new_urls)))

    # Add each URL as an import item
    for url in new_urls:
        cur.execute('''
            INSERT INTO import_items (job_id, url, status)
            VALUES (%s, %s, 'pending')
        ''', (job_id, url))

    conn.commit()
    cur.close()
    conn.close()

    return job_id, {
        'total_submitted': len(urls),
        'duplicates_in_list': len(urls) - len(unique_urls),
        'already_scraped': skipped_existing,
        'added': len(new_urls)
    }


def get_import_job(job_id):
    """Get an import job by ID with its items."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute('SELECT * FROM import_jobs WHERE id = %s', (job_id,))
    job = cur.fetchone()

    if not job:
        cur.close()
        conn.close()
        return None

    # Get items for this job
    cur.execute('''
        SELECT id, url, status, recipe_id, error_message, processed_at
        FROM import_items
        WHERE job_id = %s
        ORDER BY id
    ''', (job_id,))
    items = [dict(item) for item in cur.fetchall()]

    cur.close()
    conn.close()

    return {
        'id': job['id'],
        'status': job['status'],
        'total_urls': job['total_urls'],
        'processed_count': job['processed_count'],
        'success_count': job['success_count'],
        'error_count': job['error_count'],
        'created_at': job['created_at'],
        'completed_at': job['completed_at'],
        'items': items
    }


def get_all_import_jobs():
    """Get all import jobs (without items, for listing)."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute('''
        SELECT id, status, total_urls, processed_count, success_count, error_count, created_at, completed_at
        FROM import_jobs
        ORDER BY created_at DESC
    ''')
    jobs = [dict(job) for job in cur.fetchall()]

    cur.close()
    conn.close()

    return jobs


def get_pending_import_items(job_id, limit=10):
    """Get pending items from a job for processing."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute('''
        SELECT id, url
        FROM import_items
        WHERE job_id = %s AND status = 'pending'
        ORDER BY id
        LIMIT %s
    ''', (job_id, limit))
    items = [dict(item) for item in cur.fetchall()]

    cur.close()
    conn.close()

    return items


def get_security_items():
    """Get all security tracker items grouped by category and severity."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT * FROM security_tracker
        ORDER BY
            category,
            CASE severity
                WHEN 'critical' THEN 1
                WHEN 'high'     THEN 2
                WHEN 'medium'   THEN 3
                WHEN 'low'      THEN 4
                ELSE 5
            END,
            id
    ''')
    items = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return items


def update_security_item(item_id, status, notes=None):
    """Update the status and optional notes of a security tracker item."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        UPDATE security_tracker
        SET status = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    ''', (status, notes, item_id))
    conn.commit()
    cur.close()
    conn.close()


def update_import_item(item_id, status, recipe_id=None, error_message=None):
    """Update an import item after processing."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('''
        UPDATE import_items
        SET status = %s, recipe_id = %s, error_message = %s, processed_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING job_id
    ''', (status, recipe_id, error_message, item_id))

    result = cur.fetchone()
    job_id = result[0] if result else None

    if job_id:
        # Update job counters
        cur.execute('''
            UPDATE import_jobs
            SET processed_count = (SELECT COUNT(*) FROM import_items WHERE job_id = %s AND status != 'pending'),
                success_count = (SELECT COUNT(*) FROM import_items WHERE job_id = %s AND status = 'success'),
                error_count = (SELECT COUNT(*) FROM import_items WHERE job_id = %s AND status = 'error')
            WHERE id = %s
        ''', (job_id, job_id, job_id, job_id))

        # Check if job is complete
        cur.execute('''
            UPDATE import_jobs
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = %s AND processed_count = total_urls AND status != 'completed'
        ''', (job_id,))

    conn.commit()
    cur.close()
    conn.close()


def start_import_job(job_id):
    """Mark an import job as processing."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('''
        UPDATE import_jobs
        SET status = 'processing'
        WHERE id = %s AND status = 'pending'
    ''', (job_id,))

    conn.commit()
    cur.close()
    conn.close()


# --- Single-recipe background jobs (rescrape / ai_rematch) ---

def create_recipe_job(job_type, recipe_id):
    """Create a background job for a single-recipe operation."""
    import uuid
    job_id = str(uuid.uuid4())
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO import_jobs (id, status, job_type, recipe_id, total_urls)
        VALUES (%s, 'pending', %s, %s, 1)
    ''', (job_id, job_type, recipe_id))
    conn.commit()
    cur.close()
    conn.close()
    return job_id


def complete_recipe_job(job_id, message):
    """Mark a recipe job as completed with a result message."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        UPDATE import_jobs
        SET status = 'completed', result_message = %s, completed_at = CURRENT_TIMESTAMP
        WHERE id = %s
    ''', (message, job_id))
    conn.commit()
    cur.close()
    conn.close()


def fail_recipe_job(job_id, message):
    """Mark a recipe job as failed with an error message."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        UPDATE import_jobs
        SET status = 'failed', result_message = %s, completed_at = CURRENT_TIMESTAMP
        WHERE id = %s
    ''', (message, job_id))
    conn.commit()
    cur.close()
    conn.close()


def get_job_status(job_id):
    """Get status and result of any job by ID."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT id, status, job_type, recipe_id, result_message
        FROM import_jobs WHERE id = %s
    ''', (job_id,))
    job = cur.fetchone()
    cur.close()
    conn.close()
    return dict(job) if job else None


# --- Recipe verification ---

def get_unverified_recipes(limit=10):
    """Get random published recipes that haven't been verified yet."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT id, name, source, co2_per_serving
        FROM recipes
        WHERE is_published = TRUE
          AND source IS NOT NULL AND source != ''
          AND (verification_status = 'unverified' OR verification_status IS NULL)
        ORDER BY RANDOM()
        LIMIT %s
    ''', (limit,))
    recipes = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return recipes


def set_verification_status(recipe_id, status):
    """Set verification_status on a recipe."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('UPDATE recipes SET verification_status = %s WHERE id = %s', (status, recipe_id))
    conn.commit()
    cur.close()
    conn.close()


def get_under_review_recipes():
    """Get published recipes flagged as under_review."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT id, name, source, domain, co2_per_serving, created_at
        FROM recipes
        WHERE is_published = TRUE AND verification_status = 'under_review'
        ORDER BY created_at DESC
    ''')
    recipes = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return recipes

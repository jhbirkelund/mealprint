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

    # Create import_jobs table for batch scraping
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
            INSERT INTO recipe_ingredients (recipe_id, original_line, item, amount, unit, grams, co2, source_db)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            recipe_id,
            ing.get('original_line', ''),
            ing.get('item', ''),
            ing.get('amount', 0),
            ing.get('unit', 'g'),
            ing.get('grams', 0),
            ing.get('co2', 0),
            ing.get('source_db', '')
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

def get_all_recipes():
    """Get all recipes from the database."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute('SELECT * FROM recipes ORDER BY created_at DESC')
    recipes = cur.fetchall()

    # Convert to list of dicts with nested structures (matching JSON format)
    result = []
    for r in recipes:
        # Get ingredients for this recipe (including original_line and source_db for paper trail)
        cur.execute('SELECT original_line, item, amount, unit, grams, co2, source_db FROM recipe_ingredients WHERE recipe_id = %s', (r['id'],))
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

    # Get ingredients (including original_line and source_db for paper trail)
    cur.execute('SELECT original_line, item, amount, unit, grams, co2, source_db FROM recipe_ingredients WHERE recipe_id = %s', (recipe_id,))
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
            INSERT INTO recipe_ingredients (recipe_id, original_line, item, amount, unit, grams, co2, source_db)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            recipe_id,
            ing.get('original_line', ''),
            ing.get('item', ''),
            ing.get('amount', 0),
            ing.get('unit', 'g'),
            ing.get('grams', 0),
            ing.get('co2', 0),
            ing.get('source_db', '')
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
    """Get all ingredient names for autocomplete dropdown."""
    conn = get_connection()
    cur = conn.cursor()

    # Get unique names from all sources, preferring Danish names for DK entries
    cur.execute('''
        SELECT DISTINCT
            COALESCE(name_en, name_dk, name_fr) as display_name,
            source_db,
            confidence
        FROM climate_ingredients
        WHERE COALESCE(name_en, name_dk, name_fr) IS NOT NULL
        ORDER BY display_name
    ''')
    results = cur.fetchall()

    cur.close()
    conn.close()

    return [{'name': r[0], 'source': r[1], 'confidence': r[2]} for r in results]


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
    Uses waterfall: Danish first, then Agribalyse.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Try exact match, prioritize by confidence
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
    ''', (name, name, name))

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

def create_import_job(urls):
    """Create a new import job with a list of URLs to process."""
    job_id = str(uuid.uuid4())

    conn = get_connection()
    cur = conn.cursor()

    # Create the job
    cur.execute('''
        INSERT INTO import_jobs (id, status, total_urls)
        VALUES (%s, 'pending', %s)
    ''', (job_id, len(urls)))

    # Add each URL as an import item
    for url in urls:
        cur.execute('''
            INSERT INTO import_items (job_id, url, status)
            VALUES (%s, %s, 'pending')
        ''', (job_id, url.strip()))

    conn.commit()
    cur.close()
    conn.close()

    return job_id


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

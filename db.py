import os
import json
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
    try:
        cur.execute('ALTER TABLE recipes ADD COLUMN og_image_url TEXT')
    except:
        pass  # Column already exists
    try:
        cur.execute('ALTER TABLE recipes ADD COLUMN site_rating TEXT')
    except:
        pass  # Column already exists

    # Create recipe_ingredients table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id SERIAL PRIMARY KEY,
            recipe_id TEXT REFERENCES recipes(id) ON DELETE CASCADE,
            item TEXT,
            amount REAL,
            unit TEXT,
            grams REAL,
            co2 REAL
        )
    ''')

    # Create recipe_tags table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recipe_tags (
            id SERIAL PRIMARY KEY,
            recipe_id TEXT REFERENCES recipes(id) ON DELETE CASCADE,
            tag TEXT
        )
    ''')

    conn.commit()
    cur.close()
    conn.close()

def save_recipe_to_db(recipe_name, ingredients, total_co2, servings, nutrition=None, tags=None, source=None, og_image_url=None, site_rating=None, original_ingredients=None, rating=None):
    """Save a recipe to the database."""
    recipe_id = str(uuid.uuid4())
    co2_per_serving = round(total_co2 / servings, 3) if servings > 0 else 0

    conn = get_connection()
    cur = conn.cursor()

    # Insert recipe
    cur.execute('''
        INSERT INTO recipes (id, name, total_co2, servings, co2_per_serving, source, og_image_url, site_rating, original_ingredients,
                            rating_label, rating_color, rating_emoji,
                            nutrition_kcal, nutrition_fat, nutrition_carbs, nutrition_protein)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        nutrition.get('protein', 0) if nutrition else 0
    ))

    # Insert ingredients
    for ing in ingredients:
        cur.execute('''
            INSERT INTO recipe_ingredients (recipe_id, item, amount, unit, grams, co2)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            recipe_id,
            ing.get('item', ''),
            ing.get('amount', 0),
            ing.get('unit', 'g'),
            ing.get('grams', 0),
            ing.get('co2', 0)
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
        # Get ingredients for this recipe
        cur.execute('SELECT item, amount, unit, grams, co2 FROM recipe_ingredients WHERE recipe_id = %s', (r['id'],))
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
            }
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

    # Get ingredients
    cur.execute('SELECT item, amount, unit, grams, co2 FROM recipe_ingredients WHERE recipe_id = %s', (recipe_id,))
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
        }
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
            INSERT INTO recipe_ingredients (recipe_id, item, amount, unit, grams, co2)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            recipe_id,
            ing.get('item', ''),
            ing.get('amount', 0),
            ing.get('unit', 'g'),
            ing.get('grams', 0),
            ing.get('co2', 0)
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

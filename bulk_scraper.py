"""
Bulk Recipe Scraper

Batch import recipes from URLs for the Mealprint recipe index.
All scraped recipes are saved as unpublished for admin review.

Usage:
    # From command line
    python bulk_scraper.py urls.txt

    # Programmatically
    from bulk_scraper import run_import_job
    job_id = run_import_job(['https://example.com/recipe1', 'https://example.com/recipe2'])
"""

import sys
import time
import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse

from recipe_scrapers import scrape_me
from recipe_manager import calculate_rating
from ingredient_matcher import auto_match_ingredients, calculate_recipe_totals, load_climate_names
from db import (
    init_db,
    create_import_job,
    get_import_job,
    get_pending_import_items,
    update_import_item,
    start_import_job,
    save_recipe_to_db
)


# Rate limiting: seconds between requests
RATE_LIMIT_SECONDS = 3


class OGImageParser(HTMLParser):
    """Extract og:image meta tag from HTML."""
    def __init__(self):
        super().__init__()
        self.og_image = ""

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            attrs_dict = dict(attrs)
            if attrs_dict.get('property') == 'og:image' or attrs_dict.get('name') == 'og:image':
                self.og_image = attrs_dict.get('content', '')


def extract_og_image(url):
    """Fetch page and extract og:image URL."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            parser = OGImageParser()
            parser.feed(html)
            return parser.og_image
    except Exception:
        return ""


def scrape_recipe(url):
    """
    Scrape a single recipe URL.

    Returns:
        Dict with recipe data, or None if scraping failed.
        Dict keys: name, servings, ingredients_raw, source, og_image_url, site_rating, domain, language
    """
    try:
        scraper = scrape_me(url)

        recipe_name = scraper.title() or ""
        if not recipe_name:
            return None

        # Extract servings (just the number)
        servings_raw = scraper.yields() or "1"
        servings_match = re.search(r'\d+', str(servings_raw))
        servings = int(servings_match.group()) if servings_match else 1

        # Get ingredients
        ingredients_list = scraper.ingredients()
        if not ingredients_list:
            return None

        ingredients_raw = "\n".join(ingredients_list)

        # Extract site rating
        site_rating = ""
        try:
            ratings = scraper.ratings()
            if ratings:
                if isinstance(ratings, dict):
                    rating_val = ratings.get('rating') or ratings.get('value')
                    if rating_val:
                        site_rating = str(rating_val)
                else:
                    site_rating = str(ratings)
        except Exception:
            pass

        # Extract og:image
        og_image_url = extract_og_image(url)

        # Extract domain from URL
        parsed_url = urlparse(url)
        domain = parsed_url.netloc

        # Detect language (simple heuristic based on domain or content)
        language = detect_language(ingredients_raw, domain)

        return {
            'name': recipe_name,
            'servings': servings,
            'ingredients_raw': ingredients_raw,
            'original_ingredients': ingredients_raw,
            'source': url,
            'og_image_url': og_image_url,
            'site_rating': site_rating,
            'domain': domain,
            'language': language
        }

    except Exception as e:
        raise Exception(f"Scraping failed: {str(e)}")


def detect_language(text, domain):
    """
    Simple language detection based on content and domain.
    Returns: 'en', 'da', 'fr', or 'unknown'
    """
    text_lower = text.lower()

    # Danish indicators
    danish_words = ['og', 'med', 'til', 'eller', 'spsk', 'tsk', 'stk']
    danish_chars = ['æ', 'ø', 'å']

    # French indicators
    french_words = ['et', 'avec', 'pour', 'ou', 'cuillère', 'soupe']

    # Check domain TLD
    if domain.endswith('.dk'):
        return 'da'
    if domain.endswith('.fr'):
        return 'fr'

    # Check content
    if any(char in text_lower for char in danish_chars):
        return 'da'
    if sum(1 for word in danish_words if f' {word} ' in f' {text_lower} ') >= 2:
        return 'da'
    if sum(1 for word in french_words if f' {word} ' in f' {text_lower} ') >= 2:
        return 'fr'

    return 'en'


def process_recipe(recipe_data, climate_names):
    """
    Process scraped recipe: match ingredients and calculate CO2.

    Returns:
        Dict with calculated data, or None if processing failed.
    """
    # Auto-match ingredients
    matched = auto_match_ingredients(recipe_data['ingredients_raw'], climate_names)

    if not matched:
        return None

    # Check confidence - count how many are confident
    confident_count = sum(1 for m in matched if m['confident'])
    confidence_ratio = confident_count / len(matched) if matched else 0

    # Calculate totals
    total_co2, nutrition, detailed_ingredients = calculate_recipe_totals(matched)

    if total_co2 == 0:
        return None

    servings = recipe_data['servings']
    co2_per_serving = total_co2 / servings if servings > 0 else total_co2
    rating = calculate_rating(co2_per_serving)

    # Nutrition per serving
    nutrition_per_serving = {
        'kcal': round(nutrition['kcal'] / servings, 0) if servings > 0 else 0,
        'fat': round(nutrition['fat'] / servings, 1) if servings > 0 else 0,
        'carbs': round(nutrition['carbs'] / servings, 1) if servings > 0 else 0,
        'protein': round(nutrition['protein'] / servings, 1) if servings > 0 else 0
    }

    return {
        'ingredients': detailed_ingredients,
        'total_co2': total_co2,
        'nutrition': nutrition_per_serving,
        'rating': rating,
        'confidence_ratio': confidence_ratio
    }


def run_import_job(urls, verbose=True):
    """
    Run a bulk import job for a list of URLs.

    Args:
        urls: List of recipe URLs to scrape
        verbose: Print progress to stdout

    Returns:
        job_id of the created import job
    """
    # Initialize database
    init_db()

    # Load climate names once for all recipes
    if verbose:
        print("Loading climate database...")
    climate_names = load_climate_names()
    if verbose:
        print(f"Loaded {len(climate_names)} ingredients")

    # Create the import job
    job_id = create_import_job(urls)
    if verbose:
        print(f"\nCreated import job: {job_id}")
        print(f"Total URLs: {len(urls)}")

    # Start processing
    start_import_job(job_id)

    # Process each URL
    processed = 0
    success = 0
    errors = 0

    while True:
        # Get next batch of pending items
        pending = get_pending_import_items(job_id, limit=1)
        if not pending:
            break

        item = pending[0]
        url = item['url']
        item_id = item['id']
        processed += 1

        if verbose:
            print(f"\n[{processed}/{len(urls)}] Processing: {url}")

        try:
            # Scrape the recipe
            recipe_data = scrape_recipe(url)
            if not recipe_data:
                raise Exception("Could not extract recipe data")

            # Process and calculate CO2
            calculated = process_recipe(recipe_data, climate_names)
            if not calculated:
                raise Exception("Could not calculate CO2 (no matching ingredients)")

            # Save to database as unpublished
            recipe_id = save_recipe_to_db(
                recipe_name=recipe_data['name'],
                ingredients=calculated['ingredients'],
                total_co2=calculated['total_co2'],
                servings=recipe_data['servings'],
                nutrition=calculated['nutrition'],
                tags=[],
                source=recipe_data['source'],
                og_image_url=recipe_data['og_image_url'],
                site_rating=recipe_data['site_rating'],
                original_ingredients=recipe_data['original_ingredients'],
                rating=calculated['rating'],
                origin='bulk_scraped',
                is_published=False,
                import_job_id=job_id,
                language=recipe_data['language'],
                domain=recipe_data['domain'],
                recipe_creator='admin'
            )

            # Mark item as success
            update_import_item(item_id, 'success', recipe_id=recipe_id)
            success += 1

            if verbose:
                print(f"  ✓ Saved: {recipe_data['name']} ({calculated['total_co2']:.2f} kg CO2)")
                print(f"    Confidence: {calculated['confidence_ratio']*100:.0f}%")

        except Exception as e:
            # Mark item as error
            update_import_item(item_id, 'error', error_message=str(e))
            errors += 1

            if verbose:
                print(f"  ✗ Error: {str(e)}")

        # Rate limiting
        if processed < len(urls):
            time.sleep(RATE_LIMIT_SECONDS)

    if verbose:
        print(f"\n{'='*50}")
        print(f"Import complete!")
        print(f"  Success: {success}")
        print(f"  Errors: {errors}")
        print(f"  Job ID: {job_id}")

    return job_id


def process_import_job(job_id):
    """
    Process an existing import job (called from admin UI).

    This runs in a background thread, processing URLs one by one.
    Each completed recipe immediately appears in the review queue.
    """
    from db import get_import_job

    # Load climate names
    climate_names = load_climate_names()

    # Get the job
    job = get_import_job(job_id)
    if not job:
        return

    # Mark as processing
    start_import_job(job_id)

    # Process each pending URL
    while True:
        pending = get_pending_import_items(job_id, limit=1)
        if not pending:
            break

        item = pending[0]
        url = item['url']
        item_id = item['id']

        try:
            # Scrape the recipe
            recipe_data = scrape_recipe(url)
            if not recipe_data:
                raise Exception("Could not extract recipe data")

            # Process and calculate CO2
            calculated = process_recipe(recipe_data, climate_names)
            if not calculated:
                raise Exception("Could not calculate CO2 (no matching ingredients)")

            # Save to database as unpublished
            recipe_id = save_recipe_to_db(
                recipe_name=recipe_data['name'],
                ingredients=calculated['ingredients'],
                total_co2=calculated['total_co2'],
                servings=recipe_data['servings'],
                nutrition=calculated['nutrition'],
                tags=[],
                source=recipe_data['source'],
                og_image_url=recipe_data['og_image_url'],
                site_rating=recipe_data['site_rating'],
                original_ingredients=recipe_data['original_ingredients'],
                rating=calculated['rating'],
                origin='bulk_scraped',
                is_published=False,
                import_job_id=job_id,
                language=recipe_data['language'],
                domain=recipe_data['domain'],
                recipe_creator='admin'
            )

            # Mark item as success
            update_import_item(item_id, 'success', recipe_id=recipe_id)

        except Exception as e:
            # Mark item as error
            update_import_item(item_id, 'error', error_message=str(e))

        # Rate limiting between requests
        time.sleep(RATE_LIMIT_SECONDS)


# --- Single-recipe background workers ---

def process_rescrape_job(job_id, recipe_id):
    """
    Background worker: re-scrape a recipe from its source URL.
    Called in a thread from the admin route.
    """
    import re
    from db import get_recipe_by_id, get_connection, complete_recipe_job, fail_recipe_job
    from ingredient_matcher import parse_ingredients, load_climate_names, calculate_ingredient
    from recipe_manager import calculate_rating
    from mistral_matcher import mistral_match_batch, is_mistral_available

    try:
        recipe = get_recipe_by_id(recipe_id)
        if not recipe:
            fail_recipe_job(job_id, 'Recipe not found')
            return

        source_url = recipe.get('source')
        if not source_url:
            fail_recipe_job(job_id, 'Recipe has no source URL')
            return

        # Scrape fresh data
        scraper = scrape_me(source_url)
        new_name = scraper.title() or recipe['name']
        new_servings_raw = scraper.yields() or str(recipe['servings'])
        servings_match = re.search(r'\d+', str(new_servings_raw))
        new_servings = float(servings_match.group()) if servings_match else recipe['servings']

        ingredients_list = scraper.ingredients()
        new_original_ingredients = "\n".join(ingredients_list)

        # Parse and fuzzy-match ingredients
        climate_names = load_climate_names()
        parsed_ingredients = parse_ingredients(new_original_ingredients, climate_names)

        # Batch AI matching for low-confidence results
        ai_matches = {}
        if is_mistral_available():
            low_confidence = [
                {'original_line': ing['original_line'], 'candidates': ing['candidates'][:20]}
                for ing in parsed_ingredients
                if not ing['confident'] and ing['candidates']
            ]
            if low_confidence:
                ai_matches = mistral_match_batch(low_confidence)

        # Write to DB
        conn = get_connection()
        cur = conn.cursor()

        cur.execute('''
            UPDATE recipes SET name = %s, servings = %s, original_ingredients = %s
            WHERE id = %s
        ''', (new_name, new_servings, new_original_ingredients, recipe_id))

        cur.execute('DELETE FROM recipe_ingredients WHERE recipe_id = %s', (recipe_id,))

        mistral_count = 0
        total_co2 = 0
        for ing in parsed_ingredients:
            matched_item = ing['candidates'][0] if ing['candidates'] else ''
            matched_by = 'fuzzy'

            if ing['original_line'] in ai_matches and ai_matches[ing['original_line']]:
                matched_item = ai_matches[ing['original_line']]['match']
                matched_by = 'mistral'
                mistral_count += 1

            # Calculate grams and CO2 for this ingredient
            calc = calculate_ingredient(ing['amount'], ing['unit'], matched_item, ing['original_line']) if matched_item else None
            grams = calc['grams'] if calc else 0
            item_co2 = calc['co2'] if calc else 0
            source_db = calc['source_db'] if calc else ''
            density_applied = calc['density_applied'] if calc else None
            total_co2 += item_co2

            cur.execute('''
                INSERT INTO recipe_ingredients
                    (recipe_id, original_line, item, amount, unit, grams, co2, source_db, matched_by, density_applied)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                recipe_id,
                ing['original_line'],
                matched_item,
                ing['amount'],
                ing['unit'],
                grams,
                item_co2,
                source_db,
                matched_by,
                density_applied
            ))

        # Update recipe totals
        co2_per_serving = round(total_co2 / new_servings, 3) if new_servings else 0
        rating = calculate_rating(co2_per_serving)
        cur.execute('''
            UPDATE recipes
            SET total_co2 = %s, co2_per_serving = %s,
                rating_label = %s, rating_color = %s, rating_emoji = %s
            WHERE id = %s
        ''', (round(total_co2, 3), co2_per_serving,
              rating['label'], rating['color'], rating['emoji'],
              recipe_id))

        conn.commit()
        cur.close()
        conn.close()

        ai_msg = f' ({mistral_count} matched by AI)' if mistral_count > 0 else ''
        complete_recipe_job(job_id, f'Re-scraped successfully. {len(parsed_ingredients)} ingredients found{ai_msg}.')

    except Exception as e:
        fail_recipe_job(job_id, f'Re-scrape failed: {str(e)}')


def process_ai_rematch_job(job_id, recipe_id):
    """
    Background worker: re-match all ingredients using Mistral AI.
    Called in a thread from the admin route.
    """
    from db import get_recipe_by_id, get_connection, complete_recipe_job, fail_recipe_job
    from ingredient_matcher import parse_ingredients, load_climate_names
    from mistral_matcher import mistral_match_batch

    try:
        recipe = get_recipe_by_id(recipe_id)
        if not recipe:
            fail_recipe_job(job_id, 'Recipe not found')
            return

        climate_names = load_climate_names()
        ingredients_to_match = []

        for ing in recipe['ingredients']:
            original_line = ing.get('original_line', '')
            if not original_line or original_line == '(manually added)':
                continue
            parsed = parse_ingredients(original_line, climate_names)
            if not parsed or not parsed[0]['candidates']:
                continue
            ingredients_to_match.append({
                'original_line': original_line,
                'candidates': parsed[0]['candidates'][:20]
            })

        if not ingredients_to_match:
            complete_recipe_job(job_id, 'No ingredients to re-match.')
            return

        ai_matches = mistral_match_batch(ingredients_to_match)

        conn = get_connection()
        cur = conn.cursor()

        mistral_count = 0
        for original_line, result in ai_matches.items():
            if result and result.get('match'):
                cur.execute('''
                    UPDATE recipe_ingredients
                    SET item = %s, matched_by = 'mistral'
                    WHERE recipe_id = %s AND original_line = %s
                ''', (result['match'], recipe_id, original_line))
                mistral_count += 1

        conn.commit()
        cur.close()
        conn.close()

        if mistral_count > 0:
            complete_recipe_job(job_id, f'AI re-matched {mistral_count} ingredients.')
        else:
            complete_recipe_job(job_id, 'No ingredients were updated by AI.')

    except Exception as e:
        fail_recipe_job(job_id, f'AI re-match failed: {str(e)}')


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python bulk_scraper.py <urls_file>")
        print("       python bulk_scraper.py <url1> <url2> ...")
        sys.exit(1)

    # Check if first arg is a file
    if len(sys.argv) == 2 and sys.argv[1].endswith('.txt'):
        with open(sys.argv[1], 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    else:
        urls = sys.argv[1:]

    if not urls:
        print("No URLs provided")
        sys.exit(1)

    print(f"Mealprint Bulk Scraper")
    print(f"{'='*50}")

    run_import_job(urls)


if __name__ == '__main__':
    main()

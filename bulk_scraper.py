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

"""
Admin Blueprint for Mealprint

Password-protected admin interface for:
- Bulk URL import
- Import job monitoring
- Recipe review and approval
"""

import os
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from extensions import limiter
import json
from db import (
    get_all_import_jobs,
    get_import_job,
    create_import_job,
    start_import_job,
    get_all_recipes,
    get_recipe_by_id,
    get_connection,
    get_ingredient_by_name,
    get_security_items,
    update_security_item,
    create_recipe_job,
    get_job_status,
    get_under_review_recipes,
    set_verification_status,
    save_verification_notes,
    publish_recipe,
)
from recipe_manager import calculate_rating, CONVERSIONS, DENSITIES
from ingredient_matcher import get_ingredients_for_autocomplete
from mistral_matcher import mistral_match, mistral_match_batch, is_mistral_available

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Get admin password from environment variable
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')  # Default for local dev only


def admin_required(f):
    """Decorator to require admin authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return redirect(url_for('admin.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    """Admin login page."""
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            session['admin_authenticated'] = True
            next_url = request.args.get('next') or url_for('admin.dashboard')
            return redirect(next_url)
        else:
            return render_template('admin/login.html', error='Invalid password')
    return render_template('admin/login.html')


@admin_bp.route('/logout')
def logout():
    """Admin logout."""
    session.pop('admin_authenticated', None)
    return redirect(url_for('admin.login'))


@admin_bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard with overview stats."""
    # Get counts
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM recipes WHERE is_published = TRUE")
    published_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM recipes WHERE is_published = FALSE")
    pending_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM import_jobs")
    jobs_count = cur.fetchone()[0]

    cur.close()
    conn.close()

    return render_template('admin/dashboard.html',
        published_count=published_count,
        pending_count=pending_count,
        jobs_count=jobs_count
    )


@admin_bp.route('/import', methods=['GET', 'POST'])
@admin_required
def import_urls():
    """Submit URLs for bulk import."""
    if request.method == 'POST':
        urls_text = request.form.get('urls', '')
        urls = [url.strip() for url in urls_text.split('\n') if url.strip() and not url.strip().startswith('#')]

        if not urls:
            return render_template('admin/import.html', error='No valid URLs provided')

        # Create import job (returns tuple: job_id, stats)
        job_id, stats = create_import_job(urls)

        if job_id is None:
            # All URLs were duplicates or already scraped
            flash(f"No new URLs to import. {stats['duplicates_in_list']} duplicates, {stats['already_scraped']} already scraped.", 'error')
            return render_template('admin/import.html')

        # Show stats about what was filtered
        if stats['duplicates_in_list'] > 0 or stats['already_scraped'] > 0:
            flash(f"Added {stats['added']} URLs. Skipped {stats['duplicates_in_list']} duplicates, {stats['already_scraped']} already scraped.", 'success')

        return redirect(url_for('admin.job_detail', job_id=job_id))

    return render_template('admin/import.html')


@admin_bp.route('/jobs')
@admin_required
def jobs_list():
    """List all import jobs."""
    jobs = get_all_import_jobs()
    return render_template('admin/jobs.html', jobs=jobs)


@admin_bp.route('/jobs/<job_id>')
@admin_required
def job_detail(job_id):
    """View single import job with items."""
    job = get_import_job(job_id)
    if not job:
        return redirect(url_for('admin.jobs_list'))
    return render_template('admin/job_detail.html', job=job)


@admin_bp.route('/jobs/<job_id>/run', methods=['POST'])
@admin_required
def run_job(job_id):
    """Start processing an import job in background thread."""
    import threading
    from bulk_scraper import process_import_job

    job = get_import_job(job_id)
    if not job:
        return redirect(url_for('admin.jobs_list'))

    if job['status'] == 'pending':
        # Start processing in background thread
        thread = threading.Thread(target=process_import_job, args=(job_id,))
        thread.daemon = True
        thread.start()

        flash(f'Job started! Processing {job["total_urls"]} URLs in background.', 'success')

    return redirect(url_for('admin.review_queue'))


@admin_bp.route('/published')
@admin_required
def published_list():
    """List all published recipes."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, total_co2, co2_per_serving, source, domain, language, created_at
        FROM recipes
        WHERE is_published = TRUE
        ORDER BY created_at DESC
    """)

    columns = ['id', 'name', 'total_co2', 'co2_per_serving', 'source', 'domain', 'language', 'created_at']
    recipes = [dict(zip(columns, row)) for row in cur.fetchall()]

    cur.close()
    conn.close()

    return render_template('admin/published.html', recipes=recipes)


@admin_bp.route('/review')
@admin_required
def review_queue():
    """List unpublished recipes for review."""
    # Get unpublished recipes
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, total_co2, co2_per_serving, source, domain, language, created_at
        FROM recipes
        WHERE is_published = FALSE
        ORDER BY created_at DESC
    """)

    columns = ['id', 'name', 'total_co2', 'co2_per_serving', 'source', 'domain', 'language', 'created_at']
    recipes = [dict(zip(columns, row)) for row in cur.fetchall()]

    cur.close()
    conn.close()

    return render_template('admin/review.html', recipes=recipes)


def load_units():
    """Load units from config file."""
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'units.json')
    with open(config_path) as f:
        config = json.load(f)
    return list(config['conversions'].keys())


@admin_bp.route('/review/<recipe_id>')
@admin_required
def review_recipe(recipe_id):
    """View recipe details for review."""
    recipe = get_recipe_by_id(recipe_id)
    if not recipe:
        return redirect(url_for('admin.review_queue'))

    units = load_units()
    all_ingredients = get_ingredients_for_autocomplete()

    return render_template('admin/review_detail.html',
        recipe=recipe,
        units=units,
        all_ingredients=all_ingredients,
        ingredient_weights=CONVERSIONS['ingredients'],
        unit_conversions=CONVERSIONS['units'],
        densities=DENSITIES
    )


@admin_bp.route('/review/<recipe_id>/save', methods=['POST'])
@admin_required
def save_recipe(recipe_id):
    """Save edited recipe from admin review."""
    from recipe_manager import get_weight_in_grams, get_density, VOLUME_UNITS, UNIT_MAP

    # Get form data
    servings = float(request.form.get('servings', 1))
    tags_str = request.form.get('tags', '')
    action = request.form.get('action', 'save_draft')

    # Parse tags
    tags = [t.strip() for t in tags_str.split(',') if t.strip()]

    # Get ingredient data (parallel arrays)
    amounts = request.form.getlist('amounts')
    units = request.form.getlist('units')
    selected_matches = request.form.getlist('selected_matches')
    original_lines = request.form.getlist('original_lines')
    matched_by_list = request.form.getlist('matched_by')

    # Calculate CO2 for each ingredient
    ingredients = []
    total_co2 = 0.0
    total_nutrition = {'kcal': 0, 'fat': 0, 'carbs': 0, 'protein': 0}

    for i in range(len(amounts)):
        amount = float(amounts[i])
        unit = units[i]
        item_name = selected_matches[i]
        original_line = original_lines[i] if i < len(original_lines) else ''
        matched_by = matched_by_list[i] if i < len(matched_by_list) else 'fuzzy'

        # Convert to grams
        grams = get_weight_in_grams(amount, unit, item_name)

        # Look up climate data
        climate_data = get_ingredient_by_name(item_name)
        if climate_data:
            co2_per_kg = climate_data.get('co2_per_kg', 0)
            co2 = (grams / 1000) * co2_per_kg
            source_db = climate_data.get('source_db', 'unknown')

            # Nutrition (if available) - values in DB are per 100g
            if climate_data.get('energy_kj'):
                factor = grams / 100  # per 100g to actual amount
                total_nutrition['kcal'] += (climate_data.get('energy_kj', 0) or 0) * factor / 4.184
                total_nutrition['fat'] += (climate_data.get('fat_g', 0) or 0) * factor
                total_nutrition['carbs'] += (climate_data.get('carbs_g', 0) or 0) * factor
                total_nutrition['protein'] += (climate_data.get('protein_g', 0) or 0) * factor
        else:
            co2 = 0
            source_db = 'not_found'

        total_co2 += co2

        # Calculate density (only applies to volume units)
        clean_unit = UNIT_MAP.get(unit.lower(), unit.lower())
        density_applied = get_density(item_name) if clean_unit in VOLUME_UNITS else None

        ingredients.append({
            'original_line': original_line,
            'item': item_name,
            'amount': amount,
            'unit': unit,
            'grams': grams,
            'co2': co2,
            'source_db': source_db,
            'matched_by': matched_by,
            'density_applied': density_applied
        })

    co2_per_serving = total_co2 / servings if servings > 0 else total_co2

    # Calculate rating using shared function from recipe_manager
    rating = calculate_rating(co2_per_serving)
    rating_label = rating['label']
    rating_color = rating['color']
    rating_emoji = rating['emoji']

    # Nutrition per serving
    nutrition_per_serving = {
        'kcal': round(total_nutrition['kcal'] / servings, 1) if servings > 0 else 0,
        'fat': round(total_nutrition['fat'] / servings, 1) if servings > 0 else 0,
        'carbs': round(total_nutrition['carbs'] / servings, 1) if servings > 0 else 0,
        'protein': round(total_nutrition['protein'] / servings, 1) if servings > 0 else 0
    }

    # Determine publish status
    is_published = action == 'save_publish'

    # Update database
    conn = get_connection()
    cur = conn.cursor()

    # Update recipe
    cur.execute('''
        UPDATE recipes SET
            servings = %s,
            total_co2 = %s,
            co2_per_serving = %s,
            rating_label = %s,
            rating_color = %s,
            rating_emoji = %s,
            nutrition_kcal = %s,
            nutrition_fat = %s,
            nutrition_carbs = %s,
            nutrition_protein = %s,
            is_published = %s
        WHERE id = %s
    ''', (
        servings, total_co2, co2_per_serving,
        rating_label, rating_color, rating_emoji,
        nutrition_per_serving['kcal'], nutrition_per_serving['fat'],
        nutrition_per_serving['carbs'], nutrition_per_serving['protein'],
        is_published, recipe_id
    ))

    # Delete old ingredients
    cur.execute('DELETE FROM recipe_ingredients WHERE recipe_id = %s', (recipe_id,))

    # Insert new ingredients
    for ing in ingredients:
        cur.execute('''
            INSERT INTO recipe_ingredients (recipe_id, original_line, item, amount, unit, grams, co2, source_db, matched_by, density_applied)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (recipe_id, ing['original_line'], ing['item'], ing['amount'], ing['unit'], ing['grams'], ing['co2'], ing['source_db'], ing.get('matched_by', 'fuzzy'), ing.get('density_applied')))

    # Delete old tags and insert new ones
    cur.execute('DELETE FROM recipe_tags WHERE recipe_id = %s', (recipe_id,))
    for tag in tags:
        cur.execute('INSERT INTO recipe_tags (recipe_id, tag) VALUES (%s, %s)', (recipe_id, tag))

    conn.commit()
    cur.close()
    conn.close()

    if is_published:
        flash('Recipe saved and published', 'success')
        return redirect(url_for('admin.review_queue'))
    else:
        flash('Recipe saved as draft', 'success')
        return redirect(url_for('admin.review_recipe', recipe_id=recipe_id))


@admin_bp.route('/review/<recipe_id>/approve', methods=['POST'])
@admin_required
def approve_recipe(recipe_id):
    """Approve and publish a recipe."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("UPDATE recipes SET is_published = TRUE WHERE id = %s", (recipe_id,))

    conn.commit()
    cur.close()
    conn.close()

    flash('Recipe published successfully', 'success')
    return redirect(url_for('admin.review_queue'))


@admin_bp.route('/review/<recipe_id>/reject', methods=['POST'])
@admin_required
def reject_recipe(recipe_id):
    """Reject and delete a recipe."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM recipes WHERE id = %s", (recipe_id,))

    conn.commit()
    cur.close()
    conn.close()

    flash('Recipe deleted', 'info')
    return redirect(url_for('admin.review_queue'))


@admin_bp.route('/review/<recipe_id>/rescrape', methods=['POST'])
@admin_required
def rescrape_recipe(recipe_id):
    """Queue a background re-scrape job for this recipe."""
    import threading
    from bulk_scraper import process_rescrape_job

    recipe = get_recipe_by_id(recipe_id)
    if not recipe:
        flash('Recipe not found', 'error')
        return redirect(url_for('admin.review_queue'))

    if not recipe.get('source'):
        flash('Recipe has no source URL to re-scrape', 'error')
        return redirect(url_for('admin.review_recipe', recipe_id=recipe_id))

    job_id = create_recipe_job('rescrape', recipe_id)
    thread = threading.Thread(target=process_rescrape_job, args=(job_id, recipe_id))
    thread.daemon = True
    thread.start()

    return redirect(url_for('admin.review_recipe', recipe_id=recipe_id, job=job_id))


@admin_bp.route('/review/<recipe_id>/ai-rematch', methods=['POST'])
@admin_required
def ai_rematch_recipe(recipe_id):
    """Queue a background AI re-match job for this recipe."""
    import threading
    from bulk_scraper import process_ai_rematch_job

    if not is_mistral_available():
        flash('Mistral API key not configured. Set MISTRAL_API_KEY environment variable.', 'error')
        return redirect(url_for('admin.review_recipe', recipe_id=recipe_id))

    recipe = get_recipe_by_id(recipe_id)
    if not recipe:
        flash('Recipe not found', 'error')
        return redirect(url_for('admin.review_queue'))

    job_id = create_recipe_job('ai_rematch', recipe_id)
    thread = threading.Thread(target=process_ai_rematch_job, args=(job_id, recipe_id))
    thread.daemon = True
    thread.start()

    return redirect(url_for('admin.review_recipe', recipe_id=recipe_id, job=job_id))


@admin_bp.route('/jobs/<job_id>/status')
@admin_required
def job_status(job_id):
    """Return JSON status of a job (used by frontend polling)."""
    from flask import jsonify
    job = get_job_status(job_id)
    if not job:
        return jsonify({'status': 'not_found'}), 404
    return jsonify({
        'status': job['status'],
        'message': job['result_message'] or '',
        'job_type': job['job_type'],
        'recipe_id': job['recipe_id'],
    })


@admin_bp.route('/verify')
@admin_required
def verify_queue():
    """List under_review recipes (published and unpublished) for sign-off."""
    recipes = get_under_review_recipes()
    return render_template('admin/verify.html', recipes=recipes)


@admin_bp.route('/review/<recipe_id>/mark-verified', methods=['POST'])
@admin_required
def mark_verified(recipe_id):
    """Mark a recipe as verified. If unpublished, also publishes it."""
    recipe = get_recipe_by_id(recipe_id)
    if recipe and not recipe.get('is_published'):
        publish_recipe(recipe_id)
        set_verification_status(recipe_id, 'verified')
        flash('Recipe approved and published.', 'success')
    else:
        set_verification_status(recipe_id, 'verified')
        flash('Recipe marked as verified.', 'success')
    return redirect(url_for('admin.verify_queue'))


@admin_bp.route('/review/<recipe_id>/rematch-pipeline', methods=['POST'])
@admin_required
def rematch_pipeline(recipe_id):
    """Re-run the matching pipeline on stored original_lines for a single recipe."""
    from verify_recipes import rematch_recipe
    from ingredient_matcher import load_climate_names
    recipe = get_recipe_by_id(recipe_id)
    if not recipe:
        flash('Recipe not found.', 'error')
        return redirect(url_for('admin.verify_queue'))
    climate_names = load_climate_names()
    notes, _out, _issues = rematch_recipe({'id': recipe_id, 'name': recipe['name']}, climate_names)
    save_verification_notes(recipe_id, notes)
    n_changes = len(notes.get('changes', []))
    flash(f"Re-matched {n_changes} ingredient(s) updated." if n_changes else "Re-matched — no changes.", 'success')
    return redirect(url_for('admin.verify_queue'))


@admin_bp.route('/security')
@admin_required
def security_tracker():
    """Security and compliance risk tracker."""
    items = get_security_items()

    # Build summary counts
    open_by_severity = {}
    total_open = 0
    total_fixed = 0
    for item in items:
        if item['status'] in ('open', 'in_progress'):
            sev = item['severity']
            open_by_severity[sev] = open_by_severity.get(sev, 0) + 1
            total_open += 1
        elif item['status'] == 'fixed':
            total_fixed += 1

    return render_template('admin/security_tracker.html',
        items=items,
        open_by_severity=open_by_severity,
        total_open=total_open,
        total_fixed=total_fixed
    )


@admin_bp.route('/security/<int:item_id>/update', methods=['POST'])
@admin_required
def update_security_item_route(item_id):
    """Update status and notes for a security tracker item."""
    status = request.form.get('status', 'open')
    notes = request.form.get('notes', '').strip() or None
    if status not in ('open', 'in_progress', 'fixed', 'accepted'):
        status = 'open'
    update_security_item(item_id, status, notes)
    return redirect(url_for('admin.security_tracker') + f'#{item_id}')

    return redirect(url_for('admin.review_recipe', recipe_id=recipe_id))

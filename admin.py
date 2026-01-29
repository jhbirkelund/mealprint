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
from db import (
    get_all_import_jobs,
    get_import_job,
    create_import_job,
    start_import_job,
    get_all_recipes,
    get_recipe_by_id,
    get_connection
)

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


@admin_bp.route('/review/<recipe_id>')
@admin_required
def review_recipe(recipe_id):
    """View recipe details for review."""
    recipe = get_recipe_by_id(recipe_id)
    if not recipe:
        return redirect(url_for('admin.review_queue'))
    return render_template('admin/review_detail.html', recipe=recipe)


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

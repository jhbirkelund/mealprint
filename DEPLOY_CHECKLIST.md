# Mealprint Deployment Checklist

Run through this after every deploy to production. Check each item manually.

---

## Core (every deploy)

- [ ] Site loads at `mealprint.onrender.com`
- [ ] Explore page (`/`) shows recipe list
- [ ] Recipe page opens and displays CO2 data
- [ ] Admin login works at `/admin`
- [ ] No Python errors in Render logs

---

## Phase 8 — Background Jobs (rescrape + AI re-match)

**Rescrape:**
- [ ] Open any recipe in `/admin/review` that has a source URL
- [ ] Click "Re-scrape from Source" and confirm
- [ ] Page reloads with a **blue "Working in background…" banner** (with spinner)
- [ ] Within ~30s, banner turns **green** with a success message
- [ ] "Reload to see results" button appears — click it
- [ ] Ingredients on the recipe are updated (check count / names changed)
- [ ] No timeout error on Render (check logs)

**AI Re-match:**
- [ ] Open any recipe in `/admin/review`
- [ ] Click "Re-match with AI" and confirm
- [ ] Same blue banner appears with spinner
- [ ] Banner turns green when done (may take 15–60s depending on ingredient count)
- [ ] Reload → ingredient matches updated, "AI" badges visible where Mistral matched

**Job status endpoint:**
- [ ] Go to `/admin/jobs` — new job entries visible with type `rescrape` or `ai_rematch`

---

## Phase 8 — OG Meta Tags

- [ ] Open any recipe page, view page source (`Cmd+U`)
- [ ] Confirm these tags are present in `<head>`:
  - `og:title` — recipe name
  - `og:description` — CO2 + rating
  - `og:url` — full recipe URL
  - `og:image` — image URL (only if recipe has an image)
  - `twitter:card` — `summary_large_image`
- [ ] Paste a recipe URL into [https://www.opengraph.xyz](https://www.opengraph.xyz) — confirm preview looks correct
- [ ] Recipe without an image: confirm no `og:image` tag appears (no broken image in previews)

---

## Phase 8 — Sentry Error Monitoring (activate before real-user launch)

**Currently disabled.** Code is in `manual_app.py` and `requirements.txt`, commented out.

**When ready to activate (Phase 9 / real users):**
1. Sign up at https://sentry.io (free tier)
2. Create project → Python → Flask → copy the DSN
3. Uncomment Sentry lines in `manual_app.py` and `requirements.txt`
4. Add `SENTRY_DSN` env var in Render dashboard
5. Deploy and confirm site still loads

---

## Phase 8 — Health Endpoint

- [ ] Go to `mealprint.onrender.com/health` — confirm response is `{"status": "ok"}` with HTTP 200

---

## Phase 8 — Error Pages

- [ ] Go to `mealprint.onrender.com/this-does-not-exist` — confirm **404 page** shows with Mealprint nav and "Page not found" message
- [ ] Confirm "Browse recipes" and "Go back" buttons work
- [ ] 500 page: harder to trigger manually — just confirm it renders correctly locally by temporarily raising an exception in a route, then revert

---

## Phase 8 — Recipe Verification Tool

**Script (run locally, not on server):**
- [ ] Run `python verify_recipes.py` — confirm it prints comparisons for 10 recipes
- [ ] Confirm all checked recipes are marked `under_review` in DB
- [ ] Run `python verify_recipes.py --count 3` — confirm `--count` flag works

**Admin UI:**
- [ ] Go to `/admin/verify` — confirm flagged recipes appear
- [ ] "Edit" link opens the recipe in the review editor
- [ ] "Mark Verified" button marks the recipe verified and removes it from the list
- [ ] "Verify" appears in the admin nav bar

---

## To add as more phases ship

_(Add new sections here when new features are deployed)_

# Mealprint - Working Preferences

## UI Changes
Always propose and discuss UI changes before writing code. Get sign-off on approach first.

## quantulum3 - Known Fragility
Unmaintained package. Causes deployment failures on new Python/setuptools versions.
Currently working with `setuptools<71` pin in requirements.txt.
Plan to replace with custom regex parser (see roadmap). Only used in ingredient_matcher.py and manual_app.py for number+unit extraction.

## Transparency Reports - Data Gaps (Phase 5)
Before building, two schema additions needed:
1. `db_metadata` table (key/value) to store DB import dates: `climatedb_imported`, `agribalyse_imported`
2. Density details per ingredient — currently only store `density_applied` (bool), not the category or value used. Need to store density category + g/ml value in `recipe_ingredients` to show full conversion chain in report.

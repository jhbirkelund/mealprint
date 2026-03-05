# Ingredient Matching Issues

Running list of known issues found during recipe verification.
Fix these in bulk by updating `config/units.json`, `config/ingredient_aliases.json`, or `config/densities.json`.

Format: **pattern** → what we get vs. what we should get

---

## Open

### Unit / Weight bugs

- **`1 bay leaf`** → 100g (default piece weight). Should be ~0.5g. Add `"bay leaf": 0.5` to `ingredient_weights` in units.json. *(Found: Spanish Chickpea Soup)*
- **`tuna, canned`** → 400g (default can weight). Tuna cans are ~110-170g, not 400g. Add `"tuna": 150` to `ingredient_weights`. *(Found: Manchego-Style Spanish Eggs)*
- **`2 tbsp fresh parsley`** → 30g. Should be ~2g. Fresh herb density (0.07 g/ml) not applying for tbsp conversions — investigate density keyword matching. *(Found: Manchego-Style Spanish Eggs, Corn Fritters)*
- **`2 tbsp chives`** → 30g. Same fresh herb density bug. *(Found: Corn Fritters)*

### Ingredient match bugs

- **`sea salt & black pepper`** → matched as whole pepper vegetable (150g). Should be ignored or matched to spice. Add alias or pre-processing to split/discard this combined phrase. *(Found: Corn Fritters ×2, Chickpea Soup)*
- **`cannellini beans`** → matched to Black beans. Should match white beans / cannellini. Add alias: `"cannellini beans": "White beans"` or nearest DB match. *(Found: White Bean Soup)*
- **`celery seed`** → matched to `Celery, raw`. Should be a spice/seed entry. Add alias or check if DB has celery seed. *(Found: Chicken Pot Pie)*
- **`½ cup all-purpose flour`** → matched to wholemeal flour. Alias for `"all-purpose flour"` → `"Wheat, flour"` exists, but wholemeal is winning — investigate alias priority. *(Found: Chicken Pot Pie)*
- **`Manchego cheese`** → matched to Parmesan. Add alias `"manchego": "Cheese, hard, Manchego"` if in DB, else nearest hard cheese. *(Found: Corn Fritters)*
- **`dried tarragon`** → matched to fresh tarragon. Add alias `"dried tarragon": "Tarragon, dried"`. *(Found: White Bean Soup)*
- **`Tuscan kale` / `lacinato kale`** → going missing or mis-matched. Add alias `"tuscan kale": "Kale, raw"`, `"lacinato kale": "Kale, raw"`. *(Found: White Bean Soup)*

---

## Fixed

*(move items here once resolved, with date)*


# Ingredient Matching Issues

Running list of known issues found during recipe verification.
Fix these in bulk by updating `config/units.json`, `config/ingredient_aliases.json`, or `config/densities.json`.

Format: **pattern** → what we get vs. what we should get

---

## Open

### Unit / Weight bugs
- **`3 (15-oz.) cans white beans, drained and rinsed`** → 1200g — 3 × 400g can default; accepted (15oz ≈ 400g, close enough) *(Found: Creamy Vegan White Bean Chili)*
- **`5 cups cherry tomatoes, left whole`** → 1200g — default density 1.0; cherry tomatoes in a cup weigh ~250g, so 1200g for 5 cups is plausible; accepted *(Found: Creamy Tuscan Shrimp Pasta (Dairy-Free))*
- **`5 cups vegetable broth`** → 1200g — broth ≈ water density 1.0; 5 × 240g = 1200g; correct *(Found: CURRY SWEET POTATO + RED LENTIL SOUP)*
- **`5 cups zucchini, sliced`** → 1200g but recipe says ~650g — sliced zucchini packs loosely; true density ~0.54 g/ml; investigate adding zucchini density category

---

## Fixed

- **`20 basil leaves`** → `"basil leaves": 0.5` in ingredient_weights → 20 × 0.5 = 10g ✓ *(2026-03-05)*
- **`2 fed hvidløg`** → "hvidløg" and "fed hvidløg" aliases added → "Garlic, raw"; 2 × 5g = 10g *(2026-03-05)*
- **`12 lasagna noodles`** → `"lasagna noodle": 20` added to ingredient_weights; 12 × 20g = 240g *(2026-03-05)*
- **`tin` substring false match** → removed `"tin": 400` from ingredient_weights (was matching "Sugar, sucrose, white" because "white" contains "tin"); "tin" unit already handled by unit_map → can *(2026-03-05)*
- **`1 bay leaf`** → `"bay leaf": 0.5` added to ingredient_weights *(2026-03-05)*
- **`tuna, canned`** → `"tuna": 150` added to ingredient_weights; can handler now checks ingredient-specific weights before defaulting to 400g *(2026-03-05)*
- **`2 tbsp fresh parsley`** / **`2 tbsp chives`** → fresh_herbs density (0.07 g/ml) already in densities.json and confirmed working *(2026-03-05)*
- **`green onions` / `spring onions` / `scallions`** → piece weights (15g) already in ingredient_weights *(2026-03-05)*
- **`celery stalks`** → piece weight (40g) already in ingredient_weights; alias updated to `"Celery stalk, raw"` *(2026-03-05)*
- **`1 cup cabbage` / `1 cup kale`** → leafy_vegetables density category added (0.30 g/ml) in densities.json *(2026-03-05)*
- **`sea salt & black pepper`** → combined phrase aliases added → `"Salt, table"` *(2026-03-05)*
- **`cannellini beans`** → aliased to `"Haricot bean, dry"` (closest white bean in DB) *(2026-03-05)*
- **`celery seed`** → aliased to `"Celery stalk, raw"` (no seed entry in DB) *(2026-03-05)*
- **`½ cup all-purpose flour`** → flour aliases now point to `"Wheat flour, type 55 (for pastry)"` (Agribalyse); wholemeal flour aliased to `"Wheat, flour, wholemeal"` *(2026-03-05)*
- **`Manchego cheese`** → aliased to `"Cheddar cheese, from cow's milk"` (no Manchego in DB) *(2026-03-05)*
- **`dried tarragon`** → aliased to `"Oregano, dried"` (no dried tarragon in DB; dried herb proxy) *(2026-03-05)*
- **`Tuscan kale` / `lacinato kale`** → aliased to `"Kale, raw"` *(2026-03-05)*
- **`vegetable broth` / `vegetable stock`** → confirmed correctly aliased to `"Bouillon, vegetable"` *(2026-03-05)*


/**
 * Shared Autocomplete for Ingredient Inputs
 *
 * Usage:
 *   setupIngredientAutocomplete(allIngredients, options)
 *
 * Options:
 *   - showCandidatesOnFocus: boolean (default: false) - Show data-candidates on focus
 *   - inputSelector: string (default: '.ingredient-input')
 *   - dropdownSelector: string (default: '.autocomplete-dropdown')
 */

function setupIngredientAutocomplete(allIngredients, options = {}) {
    const config = {
        showCandidatesOnFocus: options.showCandidatesOnFocus || false,
        inputSelector: options.inputSelector || '.ingredient-input',
        dropdownSelector: options.dropdownSelector || '.autocomplete-dropdown'
    };

    // Build lookup map from name to source for candidate display
    const ingredientSourceMap = {};
    allIngredients.forEach(ing => ingredientSourceMap[ing.name] = ing.source);

    // Handle typing in input
    document.addEventListener('input', function(e) {
        if (!e.target.matches(config.inputSelector)) return;

        const input = e.target;
        const dropdown = input.nextElementSibling;
        if (!dropdown || !dropdown.matches(config.dropdownSelector)) return;

        const query = input.value.toLowerCase().trim();

        if (query.length < 2) {
            dropdown.classList.add('hidden');
            return;
        }

        // Filter ingredients - show items containing ALL search words
        const searchWords = query.split(/\s+/).filter(w => w.length > 0);
        const matches = allIngredients.filter(ing => {
            const nameLower = ing.name.toLowerCase();
            return searchWords.every(word => nameLower.includes(word));
        }).slice(0, 20);

        if (matches.length === 0) {
            dropdown.classList.add('hidden');
            return;
        }

        dropdown.innerHTML = matches.map(ing => `
            <div class="autocomplete-item px-3 py-2 hover:bg-emerald-50 cursor-pointer text-sm text-slate-700" data-value="${ing.name}">
                ${ing.name} <span class="text-slate-400">(${ing.source})</span>
            </div>
        `).join('');
        dropdown.classList.remove('hidden');
    });

    // Handle click on dropdown item
    document.addEventListener('click', function(e) {
        const item = e.target.closest('.autocomplete-item');
        if (item) {
            const container = item.closest('.relative') || item.parentElement.parentElement;
            const input = container.querySelector(config.inputSelector);
            if (input) {
                input.value = item.dataset.value || item.textContent.split(' (')[0].trim();
            }
            item.closest(config.dropdownSelector).classList.add('hidden');
            return;
        }

        // Hide dropdowns when clicking outside
        if (!e.target.matches(config.inputSelector) && !e.target.closest('.autocomplete-item')) {
            document.querySelectorAll(config.dropdownSelector).forEach(d => d.classList.add('hidden'));
        }
    });

    // Show candidates dropdown on focus (optional)
    if (config.showCandidatesOnFocus) {
        document.addEventListener('focusin', function(e) {
            if (!e.target.matches(config.inputSelector)) return;

            const input = e.target;
            const dropdown = input.nextElementSibling;
            if (!dropdown || !dropdown.matches(config.dropdownSelector)) return;

            // Store original value in case user clicks away without typing
            input.dataset.originalValue = input.value;
            input.value = '';

            // Show candidates if available
            const candidates = JSON.parse(input.dataset.candidates || '[]');
            if (candidates.length > 0) {
                dropdown.innerHTML = candidates.map(name => {
                    const source = ingredientSourceMap[name] || '';
                    return `<div class="autocomplete-item px-3 py-2 hover:bg-emerald-50 cursor-pointer text-sm text-slate-700" data-value="${name}">
                        ${name} ${source ? `<span class="text-slate-400">(${source})</span>` : ''}
                    </div>`;
                }).join('');
                dropdown.classList.remove('hidden');
            }
        });

        // Restore original value if user leaves without selecting
        document.addEventListener('focusout', function(e) {
            if (!e.target.matches(config.inputSelector)) return;

            // Small delay to allow click on dropdown item to register
            setTimeout(() => {
                if (e.target.value === '' && e.target.dataset.originalValue) {
                    e.target.value = e.target.dataset.originalValue;
                }
            }, 150);
        });
    }
}

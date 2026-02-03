"""
Mistral AI Fallback Matcher

Uses Mistral AI to match low-confidence ingredients to the climate database.
Admin-only feature - not available in general user flow.
"""

import os
import json

# Check for API key at module level
MISTRAL_API_KEY = os.environ.get('MISTRAL_API_KEY')


def mistral_match(raw_ingredient_text, candidates):
    """
    Use Mistral AI to match an ingredient to the best candidate from the climate database.

    Args:
        raw_ingredient_text: Original ingredient line (e.g., "2 cups diced tomatoes")
        candidates: List of up to 20 candidate names from fuzzy matching

    Returns:
        Dict with keys: match, confidence, reasoning
        Returns None if API key not set or API call fails.

    Example return:
        {"match": "Tomato, raw", "confidence": 0.92, "reasoning": "Diced tomatoes are raw tomatoes"}
    """
    if not MISTRAL_API_KEY:
        return None

    if not candidates:
        return None

    try:
        from mistralai import Mistral

        client = Mistral(api_key=MISTRAL_API_KEY)

        # Build the prompt
        candidates_list = "\n".join(f"- {c}" for c in candidates[:20])

        prompt = f"""You are a food ingredient matching assistant. Match the recipe ingredient to the best option from the climate database.

Recipe ingredient: "{raw_ingredient_text}"

Available options from climate database:
{candidates_list}

Instructions:
1. Select the BEST matching option from the list above
2. If none of the options are a good match, set match to "none"
3. Confidence should be 0.0-1.0 (1.0 = perfect match)

Respond with ONLY valid JSON in this exact format:
{{"match": "exact name from list or none", "confidence": 0.85, "reasoning": "brief explanation"}}"""

        response = client.chat.complete(
            model="mistral-small-latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,  # Low temperature for consistent matching
        )

        # Parse the response
        response_text = response.choices[0].message.content.strip()

        # Handle potential markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        result = json.loads(response_text)

        # Validate the match is from our candidates (or "none")
        if result.get("match") == "none":
            return None

        if result.get("match") not in candidates:
            # Mistral returned something not in our list - try to find closest match
            match_lower = result.get("match", "").lower()
            for c in candidates:
                if c.lower() == match_lower:
                    result["match"] = c
                    break
            else:
                # Still no match found, return None
                return None

        return {
            "match": result.get("match"),
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", "")
        }

    except ImportError:
        print("Warning: mistralai package not installed. Run: pip install mistralai")
        return None
    except json.JSONDecodeError as e:
        print(f"Mistral returned invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"Mistral API error: {e}")
        return None


def mistral_match_batch(ingredients_with_candidates):
    """
    Use Mistral AI to match multiple ingredients in a single API call.

    This is much faster than calling mistral_match() repeatedly, as it avoids
    multiple round-trips to the API.

    Args:
        ingredients_with_candidates: List of dicts, each with:
            - 'original_line': The raw ingredient text
            - 'candidates': List of candidate names from fuzzy matching

    Returns:
        Dict mapping original_line -> match result (or None if no match)
        Each result has: match, confidence, reasoning

    Example:
        Input: [
            {'original_line': '2 cups diced tomatoes', 'candidates': ['Tomato, raw', 'Tomato, canned']},
            {'original_line': '1 lb ground beef', 'candidates': ['Beef, mince', 'Beef, steak']}
        ]
        Output: {
            '2 cups diced tomatoes': {'match': 'Tomato, raw', 'confidence': 0.92, 'reasoning': '...'},
            '1 lb ground beef': {'match': 'Beef, mince', 'confidence': 0.95, 'reasoning': '...'}
        }
    """
    if not MISTRAL_API_KEY:
        return {}

    if not ingredients_with_candidates:
        return {}

    try:
        from mistralai import Mistral

        client = Mistral(api_key=MISTRAL_API_KEY)

        # Build the prompt with all ingredients
        ingredients_section = ""
        for i, ing in enumerate(ingredients_with_candidates, 1):
            candidates_list = ", ".join(ing['candidates'][:15])  # Limit to 15 candidates each
            ingredients_section += f"\n{i}. \"{ing['original_line']}\"\n   Options: [{candidates_list}]\n"

        prompt = f"""You are a food ingredient matching assistant. Match each recipe ingredient to the best option from its candidate list.

INGREDIENTS TO MATCH:
{ingredients_section}

Instructions:
1. For each ingredient, select the BEST matching option from its OPTIONS list
2. If none of the options are a good match, use "none" as the match
3. Confidence should be 0.0-1.0 (1.0 = perfect match)

Respond with ONLY a valid JSON array, one object per ingredient in order:
[
  {{"ingredient": "original text", "match": "exact name from options or none", "confidence": 0.85, "reasoning": "brief explanation"}},
  ...
]"""

        response = client.chat.complete(
            model="mistral-small-latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            timeout_ms=60000,  # 60 second timeout
        )

        # Parse the response
        response_text = response.choices[0].message.content.strip()

        # Handle potential markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        results = json.loads(response_text)

        # Build the result dictionary
        output = {}
        for i, result in enumerate(results):
            if i >= len(ingredients_with_candidates):
                break

            original_line = ingredients_with_candidates[i]['original_line']
            candidates = ingredients_with_candidates[i]['candidates']

            match_name = result.get("match")
            if match_name == "none" or not match_name:
                output[original_line] = None
                continue

            # Validate match is in candidates
            if match_name not in candidates:
                # Try case-insensitive match
                match_lower = match_name.lower()
                found = False
                for c in candidates:
                    if c.lower() == match_lower:
                        match_name = c
                        found = True
                        break
                if not found:
                    output[original_line] = None
                    continue

            output[original_line] = {
                "match": match_name,
                "confidence": float(result.get("confidence", 0.5)),
                "reasoning": result.get("reasoning", "")
            }

        return output

    except ImportError:
        print("Warning: mistralai package not installed. Run: pip install mistralai")
        return {}
    except json.JSONDecodeError as e:
        print(f"Mistral returned invalid JSON: {e}")
        return {}
    except Exception as e:
        print(f"Mistral API error: {e}")
        return {}


def is_mistral_available():
    """Check if Mistral matching is available (API key set)."""
    return MISTRAL_API_KEY is not None

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


def is_mistral_available():
    """Check if Mistral matching is available (API key set)."""
    return MISTRAL_API_KEY is not None

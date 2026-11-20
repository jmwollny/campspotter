"""
Every prompt sent to the LLM, in one place.

Changing a prompt changes the app's behaviour: note what changed and why in the
commit message. Templates are filled with str.format(); only the named
{placeholders} below are substituted.
"""

# Asked once per search to get the criteria used in SELECTION_SYSTEM_TEMPLATE.
CRITERIA_PROMPT = (
    "What is the criteria for a good overnight wild camping spot? Make a bulleted list with no "
    "other text. Ignore any legal considerations because the intention is to arrive late, leave "
    "early and leave no trace."
)

# Used when the LLM is unavailable or its criteria reply is empty.
DEFAULT_CRITERIA = (
    "1. Flat, even ground for comfortable sleeping and stable pitching. "
    "2. Proximity to a water source (rivers or lakes) for drinking and cooking. "
    "3. Natural shelter from wind, such as bushes, depressions, or treelines. "
    "4. Visual concealment from roads, trails, and nearby dwellings. "
    "5. Distance from livestock to avoid noise, mess, and curiosity."
)

# Placeholders: {criteria}
SELECTION_SYSTEM_TEMPLATE = (
    "You are evaluating wild camping suitability. "
    "Use this wild camping criteria to help select the best sites: {criteria}\n"
    "Prefer discreet terrain (wood/forest/scrub) away from red flags such as buildings. "
    "Return valid JSON only."
)

# Placeholders: {max_candidates}, {candidates_json}
SELECTION_USER_TEMPLATE = (
    "Evaluate these candidate sites and pick up to {max_candidates} ids that should receive "
    "detailed geometry refinement.\n"
    "Schema: keys: selected_ids (array of ids), evaluations. evaluations is an array of objects "
    "with these keys - id, suitability_score (range 0-100), reason.\n"
    "Candidate sites: {candidates_json}\n"
    "Return JSON only"
)

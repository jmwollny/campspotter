"""
Every prompt sent to the LLM, in one place.

Changing a prompt changes the app's behaviour: note what changed and why in the
commit message. Templates are filled with str.format(); only the named
{placeholders} below are substituted.
"""

# The wild camping criteria the LLM scores sites against (fixed; the app used to ask
# the LLM for them on every search, which was slow on a small local model).
CAMPING_CRITERIA = (
    "1. Flat, even ground for comfortable sleeping and stable pitching. "
    "2. Proximity to a water source (rivers or lakes) for drinking and cooking. "
    "3. Natural shelter from wind, such as bushes, depressions, or treelines. "
    "4. Visual concealment from roads, trails, and nearby dwellings. "
    "5. Distance from livestock to avoid noise, mess, and curiosity."
)

# Placeholders: {criteria}  (filled with CAMPING_CRITERIA below)
SELECTION_SYSTEM_TEMPLATE = (
    "You are evaluating wild camping suitability. "
    "Use this wild camping criteria to help select the best sites: {criteria}\n"
    "Prefer discreet terrain (wood/forest/scrub) away from red flags such as buildings. "
    "Return valid JSON only."
)

SELECTION_SYSTEM_PROMPT = SELECTION_SYSTEM_TEMPLATE.format(criteria=CAMPING_CRITERIA)

# Placeholders: {max_candidates}, {candidates_json}
SELECTION_USER_TEMPLATE = (
    "Evaluate these candidate sites and pick up to {max_candidates} ids that should receive "
    "detailed geometry refinement.\n"
    "Schema: keys: selected_ids (array of ids), evaluations. evaluations is an array of objects "
    "with these keys - id, suitability_score (range 0-100), reason.\n"
    "Candidate sites: {candidates_json}\n"
    "Return JSON only"
)

# Sent once, after a reply that wasn't valid JSON or didn't match the expected schema.
# Placeholders: {problems}, {schema_json}
STRICT_JSON_RETRY_TEMPLATE = (
    "Your previous reply could not be used: {problems}\n"
    "Reply again with only a single JSON object that matches this JSON schema exactly. "
    "No explanation, no markdown, no other text.\n"
    "Schema: {schema_json}"
)

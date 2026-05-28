"""
Skill Purchase Optimizer for Sweepy

Ported from UMAT-Kisegami's skill_purchase_optimizer.py
Adapts Kisegami's purchase planning logic to work with Sweepy's existing
scan results and infrastructure.

Features:
- Gold skill upgrade handling (buy gold -> auto-skip base)
- Fuzzy skill name matching (SequenceMatcher-based)
- End-career buy-all mode (remaining skills cheapest first)
- Budget filtering
"""

import re
from difflib import SequenceMatcher

import bot.base.log as logger

log = logger.get_logger(__name__)


def _normalize(text):
    """Lowercase and strip punctuation/extra spaces for comparison."""
    if not text:
        return ""
    normalized = re.sub(r"[^\w\s]", "", text.lower())
    return " ".join(normalized.split())


def fuzzy_match_skill_name(name_a, name_b, threshold=0.85):
    """Check if two skill names match using string similarity.

    Args:
        name_a: First skill name (e.g., from OCR)
        name_b: Second skill name (e.g., from config)
        threshold: Minimum similarity ratio (0.0-1.0)

    Returns:
        bool: True if similarity >= threshold
    """
    if not name_a or not name_b:
        return False
    return SequenceMatcher(None, _normalize(name_a), _normalize(name_b)).ratio() >= threshold


def find_matching_skill(target_name, skill_list, matched_names=None):
    """Find a skill in skill_list that matches target_name (exact -> fuzzy).

    Args:
        target_name: Config/priority skill name to search for
        skill_list: List of sweepy skill dicts with 'skill_name'/'skill_name_raw'
        matched_names: Set of already-matched skill names to skip

    Returns:
        Matching skill dict, or None
    """
    if matched_names is None:
        matched_names = set()

    target_clean = target_name.lower().strip()

    # Exact match first (try both raw and display names)
    for skill in skill_list:
        if not skill.get("available", False):
            continue
        raw = (skill.get("skill_name_raw") or "").lower().strip()
        name = (skill.get("skill_name") or "").lower().strip()
        if raw in matched_names or name in matched_names:
            continue
        if raw == target_clean or name == target_clean:
            return skill

    # Fuzzy match fallback
    best_skill = None
    best_score = 0.0
    for skill in skill_list:
        if not skill.get("available", False):
            continue
        raw = skill.get("skill_name_raw") or ""
        name = skill.get("skill_name") or ""
        if raw.lower().strip() in matched_names or name.lower().strip() in matched_names:
            continue
        for candidate in [raw, name]:
            score = SequenceMatcher(None, _normalize(candidate), _normalize(target_name)).ratio()
            if score >= 0.85 and score > best_score:
                best_skill = skill
                best_score = score

    if best_skill:
        log.debug(f"Fuzzy match: '{best_skill.get('skill_name', '')}' ~ '{target_name}' ({best_score:.2f})")

    return best_skill


def create_purchase_plan(skill_list, priority_names, gold_upgrades=None,
                         end_career=False, skip_dc=False, dc_hint_min=4):
    """Create optimized purchase plan from scanned skills.

    Ported from UMAT-Kisegami's create_purchase_plan().

    Logic:
    - Walk priority list in order
    - For gold skills: if gold available -> buy gold (auto-skip base)
    - For gold skills: if gold NOT available but base is -> buy base
    - For regular skills: buy if available
    - End-career mode: after priority skills, add all remaining (cheapest first)

    Args:
        skill_list: Sweepy scanned skill list (dicts with skill_name, skill_cost, available, gold, etc.)
        priority_names: Flat list of skill names in priority order (from config)
        gold_upgrades: Dict mapping gold_skill_name -> base_skill_name
        end_career: If True, append remaining skills sorted cheapest first
        skip_dc: If True, skip double-circle skills with low hint level
        dc_hint_min: Minimum hint level to allow double-circle skills

    Returns:
        List of skill dicts to purchase, in order
    """
    if gold_upgrades is None:
        gold_upgrades = {}

    purchase_plan = []
    matched_names = set()

    # Build reverse map: base_name -> gold_name
    base_to_gold = {}
    for gold_name, base_name in gold_upgrades.items():
        base_to_gold[base_name] = gold_name

    # Track base skills auto-granted by planned gold skills
    planned_gold_bases = set()

    log.info(f"Creating purchase plan: {len(priority_names)} priority skills, "
             f"{len(gold_upgrades)} gold upgrades, end_career={end_career}")

    # Walk priority list
    for priority_skill in priority_names:
        if priority_skill.lower().strip() in matched_names:
            continue

        # Check if this is a gold skill (key in gold_upgrades)
        if priority_skill in gold_upgrades:
            base_skill_name = gold_upgrades[priority_skill]

            # Try to find the gold skill
            gold_match = find_matching_skill(priority_skill, skill_list, matched_names)
            if gold_match:
                # Check skip_dc
                if skip_dc and gold_match.get("is_double_circle", False):
                    if int(gold_match.get("hint_level", 0)) < dc_hint_min:
                        continue

                purchase_plan.append(gold_match)
                matched_names.add((gold_match.get("skill_name_raw") or "").lower().strip())
                matched_names.add((gold_match.get("skill_name") or "").lower().strip())
                # Auto-skip the base - game grants it when gold is bought
                matched_names.add(base_skill_name.lower().strip())
                planned_gold_bases.add(base_skill_name.lower().strip())
                log.info(f"  Gold skill: {gold_match.get('skill_name', '')} "
                         f"cost={gold_match.get('skill_cost', 0)} "
                         f"(base '{base_skill_name}' auto-granted)")
            else:
                # Gold not available, try buying the base skill
                base_match = find_matching_skill(base_skill_name, skill_list, matched_names)
                if base_match:
                    if skip_dc and base_match.get("is_double_circle", False):
                        if int(base_match.get("hint_level", 0)) < dc_hint_min:
                            continue

                    purchase_plan.append(base_match)
                    matched_names.add((base_match.get("skill_name_raw") or "").lower().strip())
                    matched_names.add((base_match.get("skill_name") or "").lower().strip())
                    log.info(f"  Base skill: {base_match.get('skill_name', '')} "
                             f"cost={base_match.get('skill_cost', 0)} "
                             f"(gold '{priority_skill}' not available)")
        else:
            # Check if this base was already auto-granted by a gold skill
            if priority_skill.lower().strip() in planned_gold_bases:
                log.info(f"  Skipping '{priority_skill}' - auto-granted by gold skill")
                continue

            # Regular skill - find and buy
            match = find_matching_skill(priority_skill, skill_list, matched_names)
            if match:
                if skip_dc and match.get("is_double_circle", False):
                    if int(match.get("hint_level", 0)) < dc_hint_min:
                        continue

                purchase_plan.append(match)
                matched_names.add((match.get("skill_name_raw") or "").lower().strip())
                matched_names.add((match.get("skill_name") or "").lower().strip())
                log.info(f"  Regular skill: {match.get('skill_name', '')} "
                         f"cost={match.get('skill_cost', 0)}")

    # End-career mode: add remaining available skills, cheapest first
    if end_career:
        planned_raw = set()
        for s in purchase_plan:
            planned_raw.add((s.get("skill_name_raw") or "").lower().strip())
            planned_raw.add((s.get("skill_name") or "").lower().strip())

        remaining = [
            s for s in skill_list
            if s.get("available", False)
            and (s.get("skill_name_raw") or "").lower().strip() not in planned_raw
            and (s.get("skill_name") or "").lower().strip() not in planned_raw
        ]
        remaining.sort(key=lambda s: int(s.get("skill_cost", 99999)))

        if remaining:
            log.info(f"  End-career: adding {len(remaining)} remaining skills (cheapest first)")
            for s in remaining[:5]:
                log.info(f"    + {s.get('skill_name', '')} cost={s.get('skill_cost', 0)}")
            if len(remaining) > 5:
                log.info(f"    ... and {len(remaining) - 5} more")
            purchase_plan.extend(remaining)

    log.info(f"Purchase plan: {len(purchase_plan)} skills total")
    return purchase_plan


def filter_affordable_skills(purchase_plan, available_points):
    """Filter purchase plan to only include skills we can afford.

    Args:
        purchase_plan: List of skill dicts from create_purchase_plan()
        available_points: Available skill points

    Returns:
        tuple: (affordable_skills, total_cost, remaining_points)
    """
    affordable = []
    total_cost = 0

    log.info(f"Filtering by available points ({available_points})")

    for skill in purchase_plan:
        cost = int(skill.get("skill_cost", 0))
        if total_cost + cost <= available_points:
            affordable.append(skill)
            total_cost += cost

    remaining = available_points - total_cost
    log.info(f"Budget: {len(affordable)}/{len(purchase_plan)} affordable, "
             f"spent={total_cost}, remaining={remaining}")

    return affordable, total_cost, remaining


def flatten_priority_list(nested_list):
    """Convert sweepy's nested priority list to a flat list of names.

    Sweepy format: [["skill_a", "skill_b"], ["skill_c"]]
    Kisegami format: ["skill_a", "skill_b", "skill_c"]

    Args:
        nested_list: Sweepy's nested priority list (list of lists)

    Returns:
        Flat list of skill names in priority order
    """
    flat = []
    for tier in nested_list:
        if isinstance(tier, list):
            flat.extend(tier)
        elif isinstance(tier, str):
            flat.append(tier)
    return flat

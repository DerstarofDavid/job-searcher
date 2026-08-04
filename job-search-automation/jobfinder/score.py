"""Transparent, deterministic matching against David's saved filter."""

from __future__ import annotations

import re
from datetime import date

from .models import Evaluation, JobRecord
from .utils import company_matches, contains_phrase, fold_text, parse_date


def _find_company_status(company: str, filters: dict) -> tuple[str, str] | None:
    buckets = (
        ("already applied / waiting", filters.get("applied_waiting_companies", [])),
        ("previously rejected", filters.get("rejected_companies", [])),
        ("already reviewed or excluded", filters.get("blocked_companies", [])),
    )
    for status, companies in buckets:
        for listed in companies:
            if company_matches(company, listed):
                return status, listed
    return None


def _required_experience_years(text: str) -> int | None:
    folded = fold_text(text)
    patterns = (
        r"(?:minimum|min\.?|at least|mindestens)\s*(\d+)\+?\s*(?:years?|jahre)",
        r"(\d+)\+\s*(?:years?|jahre)\s+(?:of\s+)?(?:professional|relevant|experience|berufserfahrung)",
        r"(?:experience|berufserfahrung)\s*(?:of|von)?\s*(\d+)\+?\s*(?:years?|jahre)",
    )
    values = [int(match.group(1)) for pattern in patterns for match in re.finditer(pattern, folded)]
    return max(values) if values else None


def _location_bucket(location: str, filters: dict) -> tuple[str, float]:
    folded = fold_text(location)
    if any(token in folded for token in ("remote switzerland", "switzerland remote", "home office switzerland")):
        return "Switzerland-remote", 1.0
    for label, points in (
        ("priority commute area", 1.0),
        ("accepted Zürich/hybrid corridor", 0.8),
        ("stretch commute", 0.3),
    ):
        key = {
            "priority commute area": "priority_locations",
            "accepted Zürich/hybrid corridor": "accepted_locations",
            "stretch commute": "stretch_locations",
        }[label]
        if any(contains_phrase(location, item) for item in filters.get(key, [])):
            return label, points
    if any(contains_phrase(location, item) for item in filters.get("rejected_locations", [])):
        return "outside target geography", -1.0
    if folded in {"", "location not stated", "switzerland", "schweiz"}:
        return "location needs confirmation", 0.1
    return "unclassified Swiss/nearby location", 0.1


def evaluate(job: JobRecord, config: dict) -> Evaluation:
    filters = config["filter"]
    ranking = config["ranking"]
    text = job.searchable_text()
    folded = fold_text(text)
    title_folded = fold_text(job.title)
    reasons: list[str] = []
    risks: list[str] = []
    removals: list[str] = []
    points = 0.0

    company_status = _find_company_status(job.company, filters)
    if company_status:
        removals.append(f"{company_status[0]} company ({company_status[1]})")
    if job.closed:
        removals.append("listing is expired or explicitly closed")

    # Role relevance: title matches receive full value; description-only matches are capped.
    role_weights = filters.get("role_weights", {})
    title_roles = [(role, weight) for role, weight in role_weights.items() if contains_phrase(job.title, role)]
    body_roles = [(role, weight) for role, weight in role_weights.items() if contains_phrase(text, role)]
    matched_roles = [role for role, _ in sorted(body_roles, key=lambda item: item[1], reverse=True)[:5]]
    if title_roles:
        best_role, weight = max(title_roles, key=lambda item: item[1])
        role_points = min(3.5, weight / 10)
        points += role_points
        reasons.append(f"strong role match: {best_role}")
    elif body_roles:
        best_role, weight = max(body_roles, key=lambda item: item[1])
        points += min(2.2, weight / 14)
        reasons.append(f"ERP/business-informatics relevance in description: {best_role}")
    else:
        risks.append("role relevance is weak or unclear")

    skill_values = {
        "Microsoft Dynamics 365 Business Central": 0.55,
        "Business Central": 0.45,
        "AL": 0.35,
        "ERP": 0.3,
        "REST API": 0.18,
        "PowerShell": 0.18,
        "Git": 0.14,
        "Azure DevOps": 0.18,
        "Azure Portal": 0.14,
        "testing": 0.12,
        "debugging": 0.12,
        "documentation": 0.1,
        "requirements": 0.12,
        "stakeholder": 0.1,
        "process improvement": 0.12,
        "support": 0.12,
        "finance": 0.12,
        "bookkeeping": 0.1,
        "logistics": 0.1,
    }
    matched_skills = [skill for skill in filters.get("skill_keywords", []) if contains_phrase(text, skill)]
    skill_points = min(1.7, sum(skill_values.get(skill, 0.08) for skill in matched_skills))
    points += skill_points
    if matched_skills:
        reasons.append("matching experience: " + ", ".join(matched_skills[:5]))

    learning_hits = [word for word in filters.get("learning_keywords", []) if contains_phrase(text, word)]
    if learning_hits:
        learning_points = 1.2 if any(contains_phrase(title_folded, word) for word in learning_hits) else 0.7
        points += learning_points
        reasons.append("open to learning/early-career profile: " + ", ".join(learning_hits[:3]))
    else:
        risks.append("no explicit junior/student/learning signal")

    low, high = job.workload_min, job.workload_max
    allowed_min = int(filters["allowed_workload_min"])
    allowed_max = int(filters["allowed_workload_max"])
    if low is None or high is None:
        points -= 0.2
        risks.append("workload not stated; confirm 20–60% before applying")
    elif high < allowed_min or low > allowed_max:
        removals.append(f"workload {low}–{high}% is outside the 20–60% filter")
    elif low >= allowed_min and high <= allowed_max:
        points += 1.4
        reasons.append(f"workload fits exactly ({low}%" + (f"–{high}%" if high != low else "") + ")")
    else:
        points += 0.8
        risks.append(f"advertised range is {low}–{high}%; verify that 20–60% is selectable")

    location_label, location_points = _location_bucket(job.location, filters)
    if location_label == "outside target geography":
        removals.append(f"location outside target corridor ({job.location})")
    else:
        points += location_points
        if location_points >= 0.8:
            reasons.append(location_label)
        elif location_points <= 0.3:
            risks.append(location_label + f" ({job.location})")

    hard_language = (
        "native german",
        "german native",
        "deutsch muttersprache",
        "muttersprache deutsch",
        "german c1",
        "deutsch c1",
    )
    if any(phrase in folded for phrase in hard_language):
        removals.append("requires native/C1 German (profile is B2)")
    if re.search(r"(?:fluent|native|required|obligatoire).{0,30}(?:french|franzosisch)", folded):
        removals.append("requires fluent French")
    soft_german = any(contains_phrase(text, phrase) for phrase in filters.get("soft_risk_phrases", []) if "deutsch" in fold_text(phrase) or "german" in fold_text(phrase))
    if soft_german:
        risks.append("German wording may exceed B2; assess the interview/application language")
    if job.language.casefold().startswith("en") or any(token in folded for token in ("your role", "what you bring", "we are looking for")):
        points += 0.5
        reasons.append("English-language listing")
    elif job.language.casefold().startswith("de"):
        points += 0.15

    experience_years = _required_experience_years(text)
    if experience_years is not None and experience_years >= 2:
        removals.append(f"requires at least {experience_years} years of relevant experience")
    elif experience_years == 1:
        risks.append("asks for one year of relevant experience; six-month internship is close but not exact")

    completed_degree_patterns = (
        r"completed bachelor(?:'s)? degree required",
        r"abgeschlossenes bachelorstudium erforderlich",
        r"(?:must|required to) have (?:a )?bachelor",
    )
    if any(re.search(pattern, folded) for pattern in completed_degree_patterns):
        removals.append("requires a completed bachelor degree")
    master_required = (
        "master student required",
        "enrolled master student",
        "currently enrolled in a master",
        "laufendes masterstudium vorausgesetzt",
    )
    if any(phrase in folded for phrase in master_required):
        removals.append("requires current master-level enrolment")
    if any(contains_phrase(text, phrase) for phrase in ("currently enrolled", "currently pursuing", "du studierst", "immatrikuliert")):
        risks.append("student status/start date should be confirmed (OST begins September 2026)")

    senior = bool(re.search(r"\b(senior|lead|manager)\b", title_folded))
    if senior and not experience_years:
        risks.append("senior/lead title, but no disqualifying experience minimum was detected—stretch application")

    posted = parse_date(job.date_posted)
    if posted:
        age = (date.today() - posted).days
        if age < 0:
            risks.append("posting date appears to be in the future; verify the listing")
        elif age <= 14:
            points += 0.4
            reasons.append(f"fresh posting ({age} days old)")
        elif age <= 30:
            points += 0.2
        elif age > int(config["search"].get("stale_days", 120)):
            removals.append(f"posting is stale ({age} days old)")
        elif age > int(config["search"].get("fresh_days", 30)):
            points -= 0.4
            risks.append(f"posting is {age} days old; verify it is still active")
    else:
        risks.append("posting date not available")

    if job.verified:
        points += 0.3
        reasons.append("details verified on the public job page")
    else:
        points -= 0.3
        risks.append("search-index result only; opening could not be verified automatically")

    score = round(max(0.0, min(10.0, points)), 1)
    accepted = not removals
    if not accepted:
        tier = "removed"
    elif score >= float(ranking["minimum_top_score"]):
        tier = "top"
    elif float(ranking["low_priority_min_score"]) <= score <= float(ranking["low_priority_max_score"]):
        tier = "low"
    else:
        tier = "watch"
    return Evaluation(
        score=score,
        accepted=accepted,
        tier=tier,
        reasons=list(dict.fromkeys(reasons)),
        risks=list(dict.fromkeys(risks)),
        matched_roles=matched_roles,
        matched_skills=matched_skills,
        removal_reason="; ".join(dict.fromkeys(removals)) if removals else None,
    )


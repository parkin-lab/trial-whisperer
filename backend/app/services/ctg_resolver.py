from __future__ import annotations

import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")
NCT_ID_PATTERN = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
DRUG_TOKEN_PATTERN = re.compile(r"\b(?:[A-Za-z]{2,}-\d{2,4}|[A-Z]{2,}\d{1,4}|[A-Za-z]{4,}(?:mab|nib))\b")
TITLE_BOILERPLATE_WORDS = {"protocol", "synopsis", "version", "amendment", "confidential"}
TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
SPONSOR_STOPWORDS = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "company",
    "co",
    "gmbh",
    "sa",
    "ag",
    "plc",
    "group",
    "the",
}


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _tokenize(value: str | None) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", _normalize_text(value)) if len(token) > 2}


def _tokenize_title(value: str) -> list[str]:
    lowered = value.lower()
    return [token for token in TOKEN_PATTERN.findall(lowered)]


def _keep_meaningful_tokens(tokens: list[str]) -> list[str]:
    meaningful: list[str] = []
    for token in tokens:
        if token in TITLE_BOILERPLATE_WORDS:
            continue
        if token in TITLE_STOPWORDS:
            continue
        if len(token) <= 2 and not any(char.isdigit() for char in token):
            continue
        meaningful.append(token)
    return meaningful


def normalize_title_for_search(title: str) -> str:
    tokens = _tokenize_title(title)
    meaningful = _keep_meaningful_tokens(tokens)
    if not meaningful:
        return ""
    return " ".join(meaningful[:24])


def generate_title_variants(title: str) -> list[str]:
    normalized = normalize_title_for_search(title)
    if not normalized:
        return []

    tokens = normalized.split()
    variants: list[str] = [normalized]

    if len(tokens) > 20:
        variants.append(" ".join(tokens[:20]))
    if len(tokens) > 16:
        variants.append(" ".join(tokens[:16]))

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = _normalize_text(variant)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped


def _extract_sponsor_tokens(sponsor: str | None, max_tokens: int = 2) -> list[str]:
    if not sponsor:
        return []
    tokens = _tokenize_title(sponsor)
    filtered = [token for token in tokens if len(token) > 2 and token not in SPONSOR_STOPWORDS]
    if not filtered:
        filtered = [token for token in tokens if token not in SPONSOR_STOPWORDS]
    return filtered[:max_tokens]


def _extract_drug_like_token(trial_title: str | None) -> str | None:
    if not trial_title:
        return None
    match = DRUG_TOKEN_PATTERN.search(trial_title)
    if not match:
        return None
    return match.group(0)


def build_keyword_queries(
    indication: str | None,
    phase: str | None,
    sponsor: str | None,
    trial_title: str | None,
) -> list[str]:
    indication_text = _normalize_text(indication)
    phase_text = _normalize_text(phase)
    sponsor_tokens = _extract_sponsor_tokens(sponsor)
    sponsor_text = " ".join(sponsor_tokens).strip()
    drug_token = _extract_drug_like_token(trial_title)

    queries: list[str] = []

    base_parts = [part for part in [indication_text, phase_text, sponsor_text, drug_token] if part]
    if base_parts:
        queries.append(" ".join(base_parts))

    disease_sponsor_parts = [part for part in [indication_text, sponsor_text, drug_token, "clinical trial"] if part]
    if len(disease_sponsor_parts) > 1:
        queries.append(" ".join(disease_sponsor_parts))

    phase_disease_parts = [part for part in [indication_text, phase_text, drug_token, "study"] if part]
    if len(phase_disease_parts) > 1:
        queries.append(" ".join(phase_disease_parts))

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = _normalize_text(query)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped


def extract_nct_from_text(text: str) -> str | None:
    match = NCT_ID_PATTERN.search(text)
    return match.group(0).upper() if match else None


def _has_high_title_similarity(left: str | None, right: str | None) -> bool:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True

    left_tokens = _tokenize(left_norm)
    right_tokens = _tokenize(right_norm)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    return overlap >= 0.6


def _phase_matches(left: str | None, right: str | None) -> bool:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return False
    return left_norm in right_norm or right_norm in left_norm


def _has_sponsor_overlap(left: str | None, right: str | None) -> bool:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return False
    return bool(left_tokens & right_tokens)


def score_candidate(
    trial_title: str | None,
    trial_phase: str | None,
    trial_sponsor: str | None,
    candidate_title: str | None,
    candidate_phase: str | None,
    candidate_sponsor: str | None,
) -> float:
    confidence = 0.0
    if _has_high_title_similarity(trial_title, candidate_title):
        confidence += 0.5
    if _phase_matches(trial_phase, candidate_phase):
        confidence += 0.3
    if _has_sponsor_overlap(trial_sponsor, candidate_sponsor):
        confidence += 0.2
    return min(confidence, 1.0)

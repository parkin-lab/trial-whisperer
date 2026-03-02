from collections.abc import Sequence
from html import unescape
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

CTG_BASE_URL = "https://clinicaltrials.gov/api/v2"
DUCKDUCKGO_HTML_SEARCH_URL = "https://duckduckgo.com/html/"
RESULT_LINK_PATTERN = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
RESULT_SNIPPET_PATTERN = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(?P<snippet_div>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"<[^>]+>")


class CtgServiceError(RuntimeError):
    pass


def _study_to_result(study: dict) -> dict:
    protocol = study.get("protocolSection", {})
    id_module = protocol.get("identificationModule", {})
    design_module = protocol.get("designModule", {})
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    status_module = protocol.get("statusModule", {})

    phases = design_module.get("phases") or []
    if isinstance(phases, list):
        phase_value = ", ".join(phases)
    else:
        phase_value = str(phases)

    return {
        "nctId": id_module.get("nctId"),
        "officialTitle": id_module.get("officialTitle") or id_module.get("briefTitle"),
        "phase": phase_value,
        "sponsor": sponsor_module.get("leadSponsor", {}).get("name"),
        "overallStatus": status_module.get("overallStatus"),
    }


def first_study_result(payload: dict) -> dict | None:
    studies = payload.get("studies")
    if isinstance(studies, list) and studies:
        return _study_to_result(studies[0])
    if payload.get("protocolSection"):
        return _study_to_result(payload)
    return None


def _strip_tags(value: str) -> str:
    no_tags = TAG_PATTERN.sub(" ", value)
    return re.sub(r"\s+", " ", unescape(no_tags)).strip()


def _decode_result_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.path == "/l/" and parsed.query:
        query_params = parse_qs(parsed.query)
        encoded_target = query_params.get("uddg", [None])[0]
        if encoded_target:
            return unquote(encoded_target)
    return value


async def search_studies(query: str) -> list[dict]:
    params = {"query.term": query, "pageSize": 3}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{CTG_BASE_URL}/studies", params=params)

    if response.status_code >= 400:
        raise CtgServiceError(f"CTG search failed with status {response.status_code}")

    data = response.json()
    studies: Sequence[dict] = data.get("studies", [])
    results: list[dict] = []

    for study in studies:
        results.append(_study_to_result(study))

    return results


async def fetch_study(nct_id: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{CTG_BASE_URL}/studies/{nct_id}")

    if response.status_code >= 400:
        raise CtgServiceError(f"CTG fetch failed with status {response.status_code}")

    return response.json()


async def search_web(query: str, max_results: int = 5) -> list[dict]:
    params = {"q": query}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        response = await client.get(DUCKDUCKGO_HTML_SEARCH_URL, params=params)

    if response.status_code >= 400:
        raise CtgServiceError(f"Web search failed with status {response.status_code}")

    html = response.text
    snippets = []
    for snippet_match in RESULT_SNIPPET_PATTERN.finditer(html):
        snippets.append(_strip_tags(snippet_match.group("snippet") or snippet_match.group("snippet_div") or ""))

    results: list[dict] = []
    for index, link_match in enumerate(RESULT_LINK_PATTERN.finditer(html)):
        if len(results) >= max_results:
            break
        raw_url = link_match.group("url")
        results.append(
            {
                "url": _decode_result_url(raw_url),
                "title": _strip_tags(link_match.group("title") or ""),
                "snippet": snippets[index] if index < len(snippets) else "",
            }
        )

    return results

from collections.abc import Sequence

import httpx

CTG_BASE_URL = "https://clinicaltrials.gov/api/v2"


class CtgServiceError(RuntimeError):
    pass


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

        results.append(
            {
                "nctId": id_module.get("nctId"),
                "officialTitle": id_module.get("officialTitle") or id_module.get("briefTitle"),
                "phase": phase_value,
                "sponsor": sponsor_module.get("leadSponsor", {}).get("name"),
                "overallStatus": status_module.get("overallStatus"),
            }
        )

    return results


async def fetch_study(nct_id: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{CTG_BASE_URL}/studies/{nct_id}")

    if response.status_code >= 400:
        raise CtgServiceError(f"CTG fetch failed with status {response.status_code}")

    return response.json()

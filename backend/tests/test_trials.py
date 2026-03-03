import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import ConfidenceLevel, CriteriaType, Indication, JobStatus, TrialExtractionStatus, TrialStatus, UserRole
from app.models.trial import BackgroundJob, Trial, TrialCriteria, TrialDocument
from app.models.user import User
from app.routers import trials as trials_router
from app.services.auth import hash_password
from app.services.criteria_parser import ParsedCriterion
from app.services.trial_metadata import TrialMetadataExtraction
from app.workers import tasks

pytestmark = pytest.mark.asyncio


async def _create_user(db_session, *, email: str, role: UserRole) -> User:
    user = User(
        email=email,
        name=email.split("@")[0],
        hashed_password=hash_password("password123"),
        role=role,
        active=True,
        domain=email.split("@")[-1],
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _login(client, email: str) -> str:
    res = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert res.status_code == 200
    return res.json()["access_token"]


async def test_trial_crud_flow(client, db_session):
    pi_user = await _create_user(db_session, email="pi@example.com", role=UserRole.pi)
    owner_user = await _create_user(db_session, email="owner@example.com", role=UserRole.owner)

    pi_token = await _login(client, pi_user.email)
    owner_token = await _login(client, owner_user.email)

    create_res = await client.post(
        "/trials",
        headers={"Authorization": f"Bearer {pi_token}"},
        json={
            "nickname": "AML Study Alpha",
            "nct_id": "NCT01234567",
            "indication": "aml",
            "phase": "Phase 2",
            "sponsor": "Parkin Lab",
        },
    )
    assert create_res.status_code == 201
    trial_id = create_res.json()["id"]

    list_res = await client.get("/trials", headers={"Authorization": f"Bearer {pi_token}"})
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    get_res = await client.get(f"/trials/{trial_id}", headers={"Authorization": f"Bearer {pi_token}"})
    assert get_res.status_code == 200
    assert get_res.json()["nickname"] == "AML Study Alpha"

    archive_res = await client.post(f"/trials/{trial_id}/archive", headers={"Authorization": f"Bearer {pi_token}"})
    assert archive_res.status_code == 200
    assert archive_res.json()["status"] == "archived"

    delete_res = await client.delete(f"/trials/{trial_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert delete_res.status_code == 204

    list_after_delete = await client.get("/trials", headers={"Authorization": f"Bearer {pi_token}"})
    assert list_after_delete.status_code == 200
    assert list_after_delete.json() == []

    missing_res = await client.get(f"/trials/{trial_id}", headers={"Authorization": f"Bearer {pi_token}"})
    assert missing_res.status_code == 404


async def test_create_trial_with_upload_sets_processing_status(client, db_session, monkeypatch):
    pi_user = await _create_user(db_session, email="pi2@example.com", role=UserRole.pi)
    pi_token = await _login(client, pi_user.email)

    async def _enqueue_ok(job_id):
        del job_id
        return True

    monkeypatch.setattr(trials_router, "_enqueue_parse_job", _enqueue_ok)

    create_res = await client.post(
        "/trials/create-with-upload",
        headers={"Authorization": f"Bearer {pi_token}"},
        data={"nickname": "Upload First Trial"},
        files={"protocol": ("protocol.pdf", b"%PDF-1.4 fake trial protocol", "application/pdf")},
    )
    assert create_res.status_code == 201
    payload = create_res.json()
    assert payload["nickname"] == "Upload First Trial"
    assert payload["status"] == "draft"
    assert payload["indication"] is None
    assert payload["extraction_status"] == "processing"
    assert payload["extraction_started_at"] is not None
    assert payload["extraction_completed_at"] is None

    docs_res = await client.get(f"/trials/{payload['id']}/documents", headers={"Authorization": f"Bearer {pi_token}"})
    assert docs_res.status_code == 200
    assert len(docs_res.json()) == 1


async def test_metadata_extraction_worker_transitions_to_ready(db_session, monkeypatch):
    user = await _create_user(db_session, email="pi3@example.com", role=UserRole.pi)
    trial = Trial(
        nickname="Worker Trial",
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.processing,
        created_by=user.id,
    )
    db_session.add(trial)
    await db_session.flush()

    doc = TrialDocument(
        trial_id=trial.id,
        version=1,
        filename="protocol.pdf",
        file_path="/tmp/protocol.pdf",
        uploaded_by=user.id,
    )
    db_session.add(doc)
    await db_session.flush()

    job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial.id), "document_id": str(doc.id), "file_path": doc.file_path},
    )
    db_session.add(job)
    await db_session.commit()

    testing_session_factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", testing_session_factory)

    async def _download_file(file_path):
        del file_path
        return b"pdf bytes", "protocol.pdf"

    async def _extract_metadata(text):
        del text
        return TrialMetadataExtraction(
            indication=Indication.aml,
            nct_id="NCT12345678",
            ctg_url="https://clinicaltrials.gov/study/NCT12345678",
            trial_title="A Phase 2 Study of New Agent in AML",
            document_title="Protocol Synopsis: AML-1001",
            sponsor="Trial Sponsor",
            phase="Phase 2",
        )

    monkeypatch.setattr(tasks, "storage_download_file", _download_file)
    monkeypatch.setattr(tasks, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(tasks, "extract_text", lambda _: "mock protocol text")
    monkeypatch.setattr(tasks, "extract_trial_metadata_from_text", _extract_metadata)

    await tasks.parse_trial_document({}, str(job.id))

    updated_trial = (
        await db_session.execute(select(Trial).where(Trial.id == trial.id))
    ).scalar_one()
    updated_job = (
        await db_session.execute(select(BackgroundJob).where(BackgroundJob.id == job.id))
    ).scalar_one()

    assert updated_trial.indication == Indication.aml
    assert updated_trial.nct_id == "NCT12345678"
    assert updated_trial.trial_title == "A Phase 2 Study of New Agent in AML"
    assert updated_trial.document_title == "Protocol Synopsis: AML-1001"
    assert updated_trial.sponsor == "Trial Sponsor"
    assert updated_trial.phase == "Phase 2"
    assert updated_trial.extraction_status == TrialExtractionStatus.ready
    assert updated_trial.extraction_completed_at is not None
    assert updated_job.status == JobStatus.completed


async def test_ctg_title_fallback_auto_fills_nct_when_confidence_high(db_session, monkeypatch):
    user = await _create_user(db_session, email="pi4@example.com", role=UserRole.pi)
    trial = Trial(
        nickname="Fallback Trial",
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.processing,
        created_by=user.id,
    )
    db_session.add(trial)
    await db_session.flush()

    doc = TrialDocument(
        trial_id=trial.id,
        version=1,
        filename="protocol.pdf",
        file_path="/tmp/protocol-fallback.pdf",
        uploaded_by=user.id,
    )
    db_session.add(doc)
    await db_session.flush()

    job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial.id), "document_id": str(doc.id), "file_path": doc.file_path},
    )
    db_session.add(job)
    await db_session.commit()

    testing_session_factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", testing_session_factory)

    async def _download_file(file_path):
        del file_path
        return b"pdf bytes", "protocol.pdf"

    async def _extract_metadata(text):
        del text
        return TrialMetadataExtraction(
            indication=Indication.aml,
            sponsor="City of Hope",
            phase="Phase 2",
            trial_title="A Phase 2 Study of CAR-T in Acute Myeloid Leukemia",
            document_title="Protocol Synopsis",
            title_candidates=[
                "A Phase 2 Study of CAR-T in Acute Myeloid Leukemia",
                "Randomized Open-Label Multicenter Study of CAR-T in Patients with AML",
                "Protocol Synopsis",
            ],
        )

    search_queries: list[str] = []

    async def _search_studies(query):
        search_queries.append(query)
        if "CAR-T" not in query:
            return []
        return [
            {
                "nctId": "NCT77778888",
                "officialTitle": "A Phase 2 Study of CAR-T in Acute Myeloid Leukemia",
                "phase": "Phase 2",
                "sponsor": "City of Hope",
            }
        ]

    async def _search_web(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr(tasks, "storage_download_file", _download_file)
    monkeypatch.setattr(tasks, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(tasks, "extract_text", lambda _: "mock protocol text")
    monkeypatch.setattr(tasks, "extract_trial_metadata_from_text", _extract_metadata)
    monkeypatch.setattr(tasks, "search_studies", _search_studies)
    monkeypatch.setattr(tasks, "search_web", _search_web)

    await tasks.parse_trial_document({}, str(job.id))

    updated_trial = (await db_session.execute(select(Trial).where(Trial.id == trial.id))).scalar_one()

    assert updated_trial.nct_id == "NCT77778888"
    assert updated_trial.ctg_url == "https://clinicaltrials.gov/study/NCT77778888"
    assert updated_trial.ctg_match_confidence == pytest.approx(1.0)
    assert updated_trial.ctg_match_note == "Auto-matched from CTG title search"
    assert "A Phase 2 Study of CAR-T in Acute Myeloid Leukemia" in search_queries
    assert "Randomized Open-Label Multicenter Study of CAR-T in Patients with AML" in search_queries
    assert "Protocol Synopsis" in search_queries
    assert updated_trial.extraction_status == TrialExtractionStatus.ready


async def test_ctg_title_fallback_low_confidence_needs_manual_review(db_session, monkeypatch):
    user = await _create_user(db_session, email="pi5@example.com", role=UserRole.pi)
    trial = Trial(
        nickname="Fallback Low Confidence Trial",
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.processing,
        created_by=user.id,
    )
    db_session.add(trial)
    await db_session.flush()

    doc = TrialDocument(
        trial_id=trial.id,
        version=1,
        filename="protocol.pdf",
        file_path="/tmp/protocol-fallback-low.pdf",
        uploaded_by=user.id,
    )
    db_session.add(doc)
    await db_session.flush()

    job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial.id), "document_id": str(doc.id), "file_path": doc.file_path},
    )
    db_session.add(job)
    await db_session.commit()

    testing_session_factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", testing_session_factory)

    async def _download_file(file_path):
        del file_path
        return b"pdf bytes", "protocol.pdf"

    async def _extract_metadata(text):
        del text
        return TrialMetadataExtraction(
            indication=Indication.aml,
            sponsor="City of Hope",
            phase="Phase 2",
            trial_title="A Phase 2 Study of CAR-T in Acute Myeloid Leukemia",
            document_title="Protocol Header",
            title_candidates=[
                "A Phase 2 Study of CAR-T in Acute Myeloid Leukemia",
                "Open-Label Study in Patients with AML",
                "Protocol Header",
            ],
        )

    search_queries: list[str] = []

    async def _search_studies(query):
        search_queries.append(query)
        return [
            {
                "nctId": "NCT00001111",
                "officialTitle": "Observational Registry for Long-Term Outcomes in Solid Tumors",
                "phase": "Phase 1",
                "sponsor": "Another Sponsor",
            }
        ]

    async def _search_web(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr(tasks, "storage_download_file", _download_file)
    monkeypatch.setattr(tasks, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(tasks, "extract_text", lambda _: "mock protocol text")
    monkeypatch.setattr(tasks, "extract_trial_metadata_from_text", _extract_metadata)
    monkeypatch.setattr(tasks, "search_studies", _search_studies)
    monkeypatch.setattr(tasks, "search_web", _search_web)

    await tasks.parse_trial_document({}, str(job.id))

    updated_trial = (await db_session.execute(select(Trial).where(Trial.id == trial.id))).scalar_one()

    assert updated_trial.nct_id is None
    assert updated_trial.ctg_match_confidence == pytest.approx(0.0)
    assert updated_trial.ctg_match_note == "Candidate found; manual review recommended"
    assert updated_trial.ctg_candidate_nct_id == "NCT00001111"
    assert updated_trial.ctg_candidate_url == "https://clinicaltrials.gov/study/NCT00001111"
    assert updated_trial.ctg_candidate_title == "Observational Registry for Long-Term Outcomes in Solid Tumors"
    assert updated_trial.ctg_candidate_source == tasks.CTG_SOURCE_TITLE
    assert "A Phase 2 Study of CAR-T in Acute Myeloid Leukemia" in search_queries
    assert "Open-Label Study in Patients with AML" in search_queries
    assert "Protocol Header" in search_queries
    assert updated_trial.extraction_status == TrialExtractionStatus.needs_review


async def test_accept_ctg_candidate_endpoint_promotes_candidate(client, db_session):
    user = await _create_user(db_session, email="owner-accept@example.com", role=UserRole.owner)
    token = await _login(client, user.email)

    trial = Trial(
        nickname="Candidate Accept Trial",
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.needs_review,
        created_by=user.id,
        ctg_candidate_nct_id="NCT12344321",
        ctg_candidate_url="https://clinicaltrials.gov/study/NCT12344321",
        ctg_candidate_title="A Phase 1 Study of Candidate Agent",
        ctg_candidate_source=tasks.CTG_SOURCE_KEYWORD,
        ctg_match_note="Candidate found; manual review recommended",
        ctg_match_confidence=0.61,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    res = await client.post(
        f"/trials/{trial.id}/ctg/accept-candidate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["nct_id"] == "NCT12344321"
    assert payload["ctg_url"] == "https://clinicaltrials.gov/study/NCT12344321"
    assert payload["trial_title"] == "A Phase 1 Study of Candidate Agent"
    assert payload["ctg_match_note"] == "Candidate manually accepted"
    assert payload["ctg_candidate_nct_id"] is None
    assert payload["ctg_candidate_url"] is None
    assert payload["ctg_candidate_title"] is None
    assert payload["ctg_candidate_source"] is None


async def test_parse_worker_auto_parses_criteria(db_session, monkeypatch):
    user = await _create_user(db_session, email="pi8@example.com", role=UserRole.pi)
    trial = Trial(
        nickname="Criteria Parse Trial",
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.processing,
        created_by=user.id,
    )
    db_session.add(trial)
    await db_session.flush()

    doc = TrialDocument(
        trial_id=trial.id,
        version=1,
        filename="protocol.pdf",
        file_path="/tmp/protocol-criteria.pdf",
        uploaded_by=user.id,
    )
    db_session.add(doc)
    await db_session.flush()

    job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial.id), "document_id": str(doc.id), "file_path": doc.file_path},
    )
    db_session.add(job)
    await db_session.commit()

    testing_session_factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", testing_session_factory)

    async def _download_file(file_path):
        del file_path
        return b"pdf bytes", "protocol.pdf"

    async def _extract_metadata(text):
        del text
        return TrialMetadataExtraction(
            indication=Indication.aml,
            nct_id="NCT22223333",
            ctg_url="https://clinicaltrials.gov/study/NCT22223333",
            trial_title="A Phase 2 Study of XYZ in AML",
            document_title="Protocol Header",
            sponsor="City of Hope",
            phase="Phase 2",
        )

    async def _parse_criteria(text):
        del text
        return [
            ParsedCriterion(
                type=CriteriaType.inclusion,
                text="Age >= 18 years",
                expression={"op": "gte", "field": "age", "value": 18, "unit": "years"},
                confidence=ConfidenceLevel.high,
                manual_review_required=False,
            )
        ]

    monkeypatch.setattr(tasks, "storage_download_file", _download_file)
    monkeypatch.setattr(tasks, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(tasks, "extract_text", lambda _: "mock protocol text")
    monkeypatch.setattr(tasks, "extract_trial_metadata_from_text", _extract_metadata)
    monkeypatch.setattr(tasks, "parse_criteria_from_text", _parse_criteria)

    await tasks.parse_trial_document({}, str(job.id))

    criteria_rows = (
        await db_session.execute(select(TrialCriteria).where(TrialCriteria.trial_id == trial.id))
    ).scalars().all()
    assert len(criteria_rows) == 1
    criterion = criteria_rows[0]
    assert criterion.document_version == 1
    assert criterion.type == CriteriaType.inclusion
    assert criterion.text == "Age >= 18 years"
    assert criterion.confidence == ConfidenceLevel.high
    assert criterion.approved_at is None


async def test_ctg_title_miss_keyword_search_auto_fills_nct(db_session, monkeypatch):
    user = await _create_user(db_session, email="pi6@example.com", role=UserRole.pi)
    trial = Trial(
        nickname="Keyword Resolver Trial",
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.processing,
        created_by=user.id,
    )
    db_session.add(trial)
    await db_session.flush()

    doc = TrialDocument(
        trial_id=trial.id,
        version=1,
        filename="protocol.pdf",
        file_path="/tmp/protocol-keyword-fallback.pdf",
        uploaded_by=user.id,
    )
    db_session.add(doc)
    await db_session.flush()

    job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial.id), "document_id": str(doc.id), "file_path": doc.file_path},
    )
    db_session.add(job)
    await db_session.commit()

    testing_session_factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", testing_session_factory)

    async def _download_file(file_path):
        del file_path
        return b"pdf bytes", "protocol.pdf"

    async def _extract_metadata(text):
        del text
        return TrialMetadataExtraction(
            indication=Indication.aml,
            sponsor="City of Hope",
            phase="Phase 2",
            trial_title="A Phase 2 Study of XYZ-101 in Relapsed AML",
            document_title="Protocol Header",
            title_candidates=[
                "A Phase 2 Study of XYZ-101 in Relapsed AML",
                "Open-Label Multicenter Trial in AML",
            ],
        )

    search_queries: list[str] = []

    async def _search_studies(query):
        search_queries.append(query)
        lowered = query.lower()
        if "xyz-101" in lowered and "city" in lowered and "hope" in lowered:
            return [
                {
                    "nctId": "NCT88889999",
                    "officialTitle": "A Phase 2 Study of XYZ-101 in Relapsed AML",
                    "phase": "Phase 2",
                    "sponsor": "City of Hope",
                }
            ]
        return []

    async def _search_web(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr(tasks, "storage_download_file", _download_file)
    monkeypatch.setattr(tasks, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(tasks, "extract_text", lambda _: "mock protocol text")
    monkeypatch.setattr(tasks, "extract_trial_metadata_from_text", _extract_metadata)
    monkeypatch.setattr(tasks, "search_studies", _search_studies)
    monkeypatch.setattr(tasks, "search_web", _search_web)

    await tasks.parse_trial_document({}, str(job.id))

    updated_trial = (await db_session.execute(select(Trial).where(Trial.id == trial.id))).scalar_one()

    assert updated_trial.nct_id == "NCT88889999"
    assert updated_trial.ctg_match_note == "Auto-matched from CTG keyword search"
    assert any("xyz-101" in query.lower() and "city" in query.lower() and "hope" in query.lower() for query in search_queries)


async def test_ctg_title_miss_web_fallback_extracts_nct(db_session, monkeypatch):
    user = await _create_user(db_session, email="pi7@example.com", role=UserRole.pi)
    trial = Trial(
        nickname="Web Resolver Trial",
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.processing,
        created_by=user.id,
    )
    db_session.add(trial)
    await db_session.flush()

    doc = TrialDocument(
        trial_id=trial.id,
        version=1,
        filename="protocol.pdf",
        file_path="/tmp/protocol-web-fallback.pdf",
        uploaded_by=user.id,
    )
    db_session.add(doc)
    await db_session.flush()

    job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial.id), "document_id": str(doc.id), "file_path": doc.file_path},
    )
    db_session.add(job)
    await db_session.commit()

    testing_session_factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", testing_session_factory)

    async def _download_file(file_path):
        del file_path
        return b"pdf bytes", "protocol.pdf"

    async def _extract_metadata(text):
        del text
        return TrialMetadataExtraction(
            indication=Indication.aml,
            sponsor="City of Hope",
            phase="Phase 2",
            trial_title="A Phase 2 Study of Cell Therapy in AML",
            document_title="Protocol Header",
            title_candidates=[
                "A Phase 2 Study of Cell Therapy in AML",
                "Randomized Study in AML",
            ],
        )

    async def _search_studies(query):
        del query
        return []

    web_queries: list[str] = []

    async def _search_web(query, max_results=5):
        del max_results
        web_queries.append(query)
        return [
            {
                "url": "https://clinicaltrials.gov/study/NCT99990000",
                "title": "ClinicalTrials.gov - NCT99990000",
                "snippet": "A Phase 2 Study of Cell Therapy in AML",
            }
        ]

    async def _fetch_study(nct_id):
        assert nct_id == "NCT99990000"
        return {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT99990000",
                            "officialTitle": "A Phase 2 Study of Cell Therapy in AML",
                        },
                        "designModule": {"phases": ["Phase 2"]},
                        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "City of Hope"}},
                    }
                }
            ]
        }

    monkeypatch.setattr(tasks, "storage_download_file", _download_file)
    monkeypatch.setattr(tasks, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(tasks, "extract_text", lambda _: "mock protocol text")
    monkeypatch.setattr(tasks, "extract_trial_metadata_from_text", _extract_metadata)
    monkeypatch.setattr(tasks, "search_studies", _search_studies)
    monkeypatch.setattr(tasks, "search_web", _search_web)
    monkeypatch.setattr(tasks, "fetch_study", _fetch_study)

    await tasks.parse_trial_document({}, str(job.id))

    updated_trial = (await db_session.execute(select(Trial).where(Trial.id == trial.id))).scalar_one()

    assert updated_trial.nct_id == "NCT99990000"
    assert updated_trial.ctg_match_note == "Auto-matched from CTG web fallback"
    assert any(query.startswith("site:clinicaltrials.gov ") for query in web_queries)

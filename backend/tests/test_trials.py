import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import Indication, JobStatus, TrialExtractionStatus, TrialStatus, UserRole
from app.models.trial import BackgroundJob, Trial, TrialDocument
from app.models.user import User
from app.routers import trials as trials_router
from app.services.auth import hash_password
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
        )

    async def _search_studies(query):
        assert query == "A Phase 2 Study of CAR-T in Acute Myeloid Leukemia"
        return [
            {
                "nctId": "NCT77778888",
                "officialTitle": "A Phase 2 Study of CAR-T in Acute Myeloid Leukemia",
                "phase": "Phase 2",
                "sponsor": "City of Hope",
            }
        ]

    monkeypatch.setattr(tasks, "storage_download_file", _download_file)
    monkeypatch.setattr(tasks, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(tasks, "extract_text", lambda _: "mock protocol text")
    monkeypatch.setattr(tasks, "extract_trial_metadata_from_text", _extract_metadata)
    monkeypatch.setattr(tasks, "search_studies", _search_studies)

    await tasks.parse_trial_document({}, str(job.id))

    updated_trial = (await db_session.execute(select(Trial).where(Trial.id == trial.id))).scalar_one()

    assert updated_trial.nct_id == "NCT77778888"
    assert updated_trial.ctg_url == "https://clinicaltrials.gov/study/NCT77778888"
    assert updated_trial.ctg_match_confidence == pytest.approx(1.0)
    assert updated_trial.ctg_match_note == "Auto-matched from title search"
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
        )

    async def _search_studies(query):
        assert query == "A Phase 2 Study of CAR-T in Acute Myeloid Leukemia"
        return [
            {
                "nctId": "NCT00001111",
                "officialTitle": "Observational Registry for Long-Term Outcomes in Solid Tumors",
                "phase": "Phase 1",
                "sponsor": "Another Sponsor",
            }
        ]

    monkeypatch.setattr(tasks, "storage_download_file", _download_file)
    monkeypatch.setattr(tasks, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(tasks, "extract_text", lambda _: "mock protocol text")
    monkeypatch.setattr(tasks, "extract_trial_metadata_from_text", _extract_metadata)
    monkeypatch.setattr(tasks, "search_studies", _search_studies)

    await tasks.parse_trial_document({}, str(job.id))

    updated_trial = (await db_session.execute(select(Trial).where(Trial.id == trial.id))).scalar_one()

    assert updated_trial.nct_id is None
    assert updated_trial.ctg_match_confidence == pytest.approx(0.0)
    assert updated_trial.ctg_match_note == "Candidate found; manual review recommended"
    assert updated_trial.extraction_status == TrialExtractionStatus.needs_review

from app.models.enums import UserRole
from app.models.user import User
from app.services.auth import hash_password


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

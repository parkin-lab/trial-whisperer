from sqlalchemy import select

from app.models.user import DomainAllowlist, User
from app.services.auth import create_verification_token


async def test_register_verify_login_me(client, db_session):
    db_session.add(DomainAllowlist(domain="example.com", added_by=None))
    await db_session.commit()

    register_res = await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "password123", "name": "Alice"},
    )
    assert register_res.status_code == 201

    user = (await db_session.execute(select(User).where(User.email == "alice@example.com"))).scalar_one()
    assert user.active is False

    token = create_verification_token(user.id)
    verify_res = await client.post("/auth/verify", params={"token": token})
    assert verify_res.status_code == 200

    login_res = await client.post("/auth/login", json={"email": "alice@example.com", "password": "password123"})
    assert login_res.status_code == 200

    access_token = login_res.json()["access_token"]
    me_res = await client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "alice@example.com"


async def test_register_rejects_non_allowlisted_domain(client):
    register_res = await client.post(
        "/auth/register",
        json={"email": "alice@blocked.com", "password": "password123", "name": "Alice"},
    )
    assert register_res.status_code == 403

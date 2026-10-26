"""Account basics: verify email, reset and change password, change email, sign out everywhere, invites and roles."""

import re
import uuid

from tests.conftest import API, signup


def token_in(mail: dict) -> str:
    return re.search(r"token=([A-Za-z0-9._\-]+)", mail["html"]).group(1)


def register(client, prefix="acct"):
    email = f"{prefix}-{uuid.uuid4().hex}@example.com"
    client.post(f"{API}/auth/register", json={"email": email, "password": "password123"})
    tokens = client.post(f"{API}/auth/login", json={"email": email, "password": "password123"}).json()
    return email, {"Authorization": f"Bearer {tokens['access_token']}"}, tokens["refresh_token"]


def test_signup_sends_a_verification_link_that_verifies(client, outbox):
    email, headers, _ = register(client)
    assert client.get(f"{API}/auth/me", headers=headers).json()["email_verified"] is False
    mail = next(m for m in outbox if m["to"] == email)
    assert client.post(f"{API}/auth/verify-email", json={"token": token_in(mail)}).status_code == 200
    assert client.get(f"{API}/auth/me", headers=headers).json()["email_verified"] is True
    assert client.post(f"{API}/auth/verify-email", json={"token": "nonsense"}).status_code == 400


def test_password_reset_works_once_and_signs_out_old_sessions(client, outbox):
    email, _, refresh = register(client)
    assert client.post(f"{API}/auth/forgot-password", json={"email": email.upper()}).json() == {"ok": True}
    assert client.post(f"{API}/auth/forgot-password", json={"email": "nobody@example.com"}).json() == {"ok": True}
    token = token_in([m for m in outbox if m["to"] == email and "Reset" in m["subject"]][-1])

    assert client.post(f"{API}/auth/reset-password", json={"token": token, "password": "newpassword1"}).status_code == 200
    assert client.post(f"{API}/auth/reset-password", json={"token": token, "password": "another123"}).status_code == 400
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": email, "password": "newpassword1"}).status_code == 200


def test_change_password_needs_the_current_one(client):
    email, headers, refresh = register(client)
    wrong = client.post(f"{API}/auth/change-password", json={"current_password": "nope", "new_password": "newpassword1"}, headers=headers)
    assert wrong.status_code == 400
    ok = client.post(f"{API}/auth/change-password", json={"current_password": "password123", "new_password": "newpassword1"}, headers=headers)
    assert ok.status_code == 200
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": email, "password": "newpassword1"}).status_code == 200


def test_email_changes_only_after_the_new_address_confirms(client, outbox):
    email, headers, _ = register(client)
    new = f"new-{uuid.uuid4().hex}@example.com"
    assert client.post(f"{API}/auth/change-email", json={"new_email": new, "password": "bad"}, headers=headers).status_code == 400
    assert client.post(f"{API}/auth/change-email", json={"new_email": new, "password": "password123"}, headers=headers).status_code == 200
    assert client.get(f"{API}/auth/me", headers=headers).json()["email"] == email
    client.post(f"{API}/auth/verify-email", json={"token": token_in(next(m for m in outbox if m["to"] == new))})
    assert client.get(f"{API}/auth/me", headers=headers).json()["email"] == new


def test_name_and_sign_out_everywhere(client):
    _, headers, refresh = register(client)
    assert client.patch(f"{API}/auth/me", json={"name": " Ada "}, headers=headers).json()["name"] == "Ada"
    client.post(f"{API}/auth/logout-all", headers=headers)
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": refresh}).status_code == 401


def test_invite_by_email_then_accept_after_signup(client, outbox):
    owner = signup(client, "owner")
    workspace = client.get(f"{API}/workspaces", headers=owner).json()[0]["id"]
    guest = f"guest-{uuid.uuid4().hex}@example.com"
    sent = client.post(f"{API}/workspaces/{workspace}/members", json={"email": guest, "role": "admin"}, headers=owner).json()
    assert sent["invited"] is True
    assert [i["email"] for i in client.get(f"{API}/workspaces/{workspace}/invites", headers=owner).json()] == [guest]
    token = token_in(next(m for m in outbox if m["to"] == guest))

    stranger = signup(client, "stranger")
    assert client.post(f"{API}/workspaces/invites/accept", json={"token": token}, headers=stranger).status_code == 403

    client.post(f"{API}/auth/register", json={"email": guest, "password": "password123"})
    guest_headers = {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"email": guest, "password": "password123"}).json()["access_token"]}
    joined = client.post(f"{API}/workspaces/invites/accept", json={"token": token}, headers=guest_headers)
    assert joined.status_code == 200 and joined.json()["role"] == "admin"
    assert workspace in {w["id"] for w in client.get(f"{API}/workspaces", headers=guest_headers).json()}
    assert client.get(f"{API}/workspaces/{workspace}/invites", headers=owner).json() == []
    assert client.post(f"{API}/workspaces/invites/accept", json={"token": token}, headers=guest_headers).status_code == 400


def test_roles_rename_and_last_owner(client):
    owner = signup(client, "owner")
    me = client.get(f"{API}/auth/me", headers=owner).json()["id"]
    workspace = client.get(f"{API}/workspaces", headers=owner).json()[0]["id"]
    assert client.patch(f"{API}/workspaces/{workspace}", json={"name": "Halden team"}, headers=owner).json()["name"] == "Halden team"
    assert client.patch(f"{API}/workspaces/{workspace}/members/{me}", json={"role": "member"}, headers=owner).status_code == 409

    email, member_headers, _ = register(client, "member")
    added = client.post(f"{API}/workspaces/{workspace}/members", json={"email": email}, headers=owner).json()
    assert added["invited"] is False
    assert client.patch(f"{API}/workspaces/{workspace}", json={"name": "Mine"}, headers=member_headers).status_code == 403
    promoted = client.patch(f"{API}/workspaces/{workspace}/members/{added['user_id']}", json={"role": "admin"}, headers=owner)
    assert promoted.json()["role"] == "admin"
    assert client.patch(f"{API}/workspaces/{workspace}/members/{me}", json={"role": "member"}, headers=member_headers).status_code == 403


def test_google_sign_in_creates_a_verified_trial_account_then_logs_it_in(client, monkeypatch, trial_signups):
    email = f"g-{uuid.uuid4().hex}@example.com"
    monkeypatch.setattr("app.auth.google.verified_email", lambda token: email if token == "good" else None)
    assert client.post(f"{API}/auth/google", json={"credential": "forged"}).status_code == 401

    first = client.post(f"{API}/auth/google", json={"credential": "good"}).json()
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    me = client.get(f"{API}/auth/me", headers=headers).json()
    assert me["email"] == email and me["email_verified"] is True
    workspace = client.get(f"{API}/workspaces", headers=headers).json()[0]["id"]
    assert client.get(f"{API}/workspaces/{workspace}/billing", headers=headers).json()["plan"] == "free"

    again = client.post(f"{API}/auth/google", json={"credential": "good"}).json()
    again_headers = {"Authorization": f"Bearer {again['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=again_headers).json()["id"] == me["id"]  # same account, not a new one


def test_google_tokens_must_be_for_our_client_and_verified(monkeypatch):
    from app.auth import google

    monkeypatch.setattr(google.settings, "google_client_id", "ours.apps.googleusercontent.com")

    class Reply:
        def __init__(self, claims):
            self.status_code, self.claims = 200, claims

        def json(self):
            return self.claims

    good = {"aud": "ours.apps.googleusercontent.com", "iss": "https://accounts.google.com", "email": "A@x.com", "email_verified": "true"}
    for claims, expected in [
        (good, "a@x.com"),
        ({**good, "aud": "someone-else"}, None),
        ({**good, "email_verified": "false"}, None),
        ({**good, "iss": "evil.example"}, None),
    ]:
        monkeypatch.setattr(google.httpx, "get", lambda *a, **k: Reply(claims))
        assert google.verified_email("token") == expected

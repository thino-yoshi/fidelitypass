import pytest
from unittest.mock import MagicMock
import bcrypt


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


class TestLogin:
    def test_login_success(self, client, mock_supabase):
        password = "password123"
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
            "id": "user-123",
            "email": "test@example.com",
            "password_hash": _hash(password),
            "user_type": "client",
            "name": "Test User",
        }]

        res = client.post("/auth/login", json={"email": "test@example.com", "password": password})

        assert res.status_code == 200
        data = res.json()
        assert "token" in data
        assert data["user_type"] == "client"

    def test_login_wrong_password(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
            "id": "user-123",
            "email": "test@example.com",
            "password_hash": _hash("correct_password"),
            "user_type": "client",
            "name": "Test User",
        }]

        res = client.post("/auth/login", json={"email": "test@example.com", "password": "wrong_password"})

        assert res.status_code == 401
        assert "incorrect" in res.json()["detail"].lower()

    def test_login_unknown_email(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        res = client.post("/auth/login", json={"email": "nobody@example.com", "password": "any"})

        assert res.status_code == 401


class TestRegister:
    def test_register_success(self, client, mock_supabase):
        # Email non existant
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        # Insert retourne le nouvel utilisateur
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{
            "id": "new-user-id",
            "email": "new@example.com",
            "user_type": "client",
            "name": "New User",
        }]

        res = client.post("/auth/register", json={
            "email": "new@example.com",
            "password": "password123",
            "name": "New User",
            "user_type": "client",
        })

        assert res.status_code == 200
        assert "token" in res.json()

    def test_register_duplicate_email(self, client, mock_supabase):
        # Email déjà existant
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "existing-user"}
        ]

        res = client.post("/auth/register", json={
            "email": "existing@example.com",
            "password": "password123",
            "name": "User",
            "user_type": "client",
        })

        assert res.status_code == 400
        assert "déjà" in res.json()["detail"]

    def test_register_merchant_without_code(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        res = client.post("/auth/register", json={
            "email": "merchant@example.com",
            "password": "password123",
            "name": "Merchant",
            "user_type": "merchant",
        })

        assert res.status_code == 400
        assert "code" in res.json()["detail"].lower()

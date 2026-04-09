import pytest
from unittest.mock import MagicMock, patch
from jose import jwt
from datetime import datetime, timedelta


def _make_dynamic_token(qr_token: str, secret: str) -> str:
    payload = {
        "qr_token": qr_token,
        "card_id": "card-123",
        "exp": datetime.utcnow() + timedelta(seconds=60),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


class TestScan:
    def test_scan_valid_qr(self, client, mock_supabase, merchant_token):
        qr_token = "valid-qr-token"
        dynamic_token = _make_dynamic_token(qr_token, "test-secret-key-for-tests")

        # Carte trouvée, appartient au marchand
        card = {
            "id": "card-123",
            "client_id": "client-456",
            "merchant_id": "test-merchant-id",
            "stamps_count": 3,
            "qr_token": qr_token,
        }
        merchant = {
            "id": "test-merchant-id",
            "business_name": "Café Test",
            "stamps_required": 10,
            "reward_description": "Café gratuit",
        }

        table_mock = MagicMock()
        mock_supabase.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.execute.return_value.data = [card]
        table_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [merchant]
        table_mock.update.return_value.eq.return_value.execute.return_value.data = []
        table_mock.insert.return_value.execute.return_value.data = []

        res = client.post(
            "/scan/",
            json={"qr_token": dynamic_token},
            headers={"Authorization": f"Bearer {merchant_token}"},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["stamps_count"] == 4
        assert data["reward_reached"] is False

    def test_scan_invalid_qr(self, client, mock_supabase, merchant_token):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        res = client.post(
            "/scan/",
            json={"qr_token": "invalid-token"},
            headers={"Authorization": f"Bearer {merchant_token}"},
        )

        assert res.status_code == 404

    def test_scan_forbidden_for_client(self, client, mock_supabase, auth_token):
        res = client.post(
            "/scan/",
            json={"qr_token": "any-token"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        assert res.status_code == 403

    def test_scan_reward_reached(self, client, mock_supabase, merchant_token):
        qr_token = "reward-qr-token"
        dynamic_token = _make_dynamic_token(qr_token, "test-secret-key-for-tests")

        card = {
            "id": "card-123",
            "client_id": "client-456",
            "merchant_id": "test-merchant-id",
            "stamps_count": 9,
            "qr_token": qr_token,
        }
        merchant = {
            "id": "test-merchant-id",
            "business_name": "Café Test",
            "stamps_required": 10,
            "reward_description": "Café gratuit",
        }

        table_mock = MagicMock()
        mock_supabase.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.execute.return_value.data = [card]
        table_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [merchant]
        table_mock.update.return_value.eq.return_value.execute.return_value.data = []
        table_mock.insert.return_value.execute.return_value.data = []

        res = client.post(
            "/scan/",
            json={"qr_token": dynamic_token},
            headers={"Authorization": f"Bearer {merchant_token}"},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["reward_reached"] is True
        assert data["stamps_count"] == 0  # Reset après récompense

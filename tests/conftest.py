import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Mock Supabase et Firebase avant l'import de l'app
import sys

# Mock firebase_admin
firebase_mock = MagicMock()
firebase_mock._apps = {}
sys.modules['firebase_admin'] = firebase_mock
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.messaging'] = MagicMock()

# Mock google.oauth2
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.id_token'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()

# Variables d'env pour les tests
import os
os.environ.setdefault('SUPABASE_URL', 'https://test.supabase.co')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-key')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-tests')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-client-id')


@pytest.fixture
def mock_supabase():
    """Mock Supabase client pour les tests."""
    with patch('app.database.supabase') as mock:
        yield mock


@pytest.fixture
def client(mock_supabase):
    """Client de test FastAPI."""
    with patch('app.database.create_client', return_value=MagicMock()):
        from app.main import app
        return TestClient(app)


@pytest.fixture
def auth_token():
    """Génère un token JWT valide pour les tests."""
    from jose import jwt
    from datetime import datetime, timedelta
    payload = {
        "sub": "test-user-id",
        "user_type": "client",
        "exp": datetime.utcnow() + timedelta(days=1),
    }
    return jwt.encode(payload, "test-secret-key-for-tests", algorithm="HS256")


@pytest.fixture
def merchant_token():
    """Génère un token JWT marchand pour les tests."""
    from jose import jwt
    from datetime import datetime, timedelta
    payload = {
        "sub": "test-merchant-id",
        "user_type": "merchant",
        "exp": datetime.utcnow() + timedelta(days=1),
    }
    return jwt.encode(payload, "test-secret-key-for-tests", algorithm="HS256")

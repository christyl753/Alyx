import json
import pytest
from api import app

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_chat_endpoint_echo_prompt(client):
    """Ensure the /api/chat endpoint returns a valid response for a simple prompt."""
    resp = client.post('/api/chat', json={'message': 'Bonjour', 'vocal': False})
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'message' in data
    assert isinstance(data['message'], str)

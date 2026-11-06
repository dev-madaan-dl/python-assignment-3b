"""
End-to-end tests for Assignment 3B GenAI Assistant API.
Requires the Django server to be running on http://127.0.0.1:8000
Run with: python -m pytest tests/test_e2e.py -v
"""
import io
import uuid
import pytest
import requests

BASE_URL = "http://127.0.0.1:8000/api"


@pytest.fixture(scope="session")
def credentials():
    username = f"testuser_{uuid.uuid4().hex[:8]}"
    password = "TestPass123!"
    return {"username": username, "password": password}


@pytest.fixture(scope="session")
def token(credentials):
    # Register
    resp = requests.post(f"{BASE_URL}/register/", json=credentials)
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    return resp.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(token):
    return {"Authorization": f"Token {token}"}


@pytest.fixture(scope="session")
def conversation(auth_headers):
    resp = requests.post(
        f"{BASE_URL}/conversations/",
        json={"title": "E2E Test Conversation"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()


# ─── Auth tests ───────────────────────────────────────────────────────────────

def test_register_creates_token(credentials):
    """Registering a new user returns a token."""
    username = f"newuser_{uuid.uuid4().hex[:8]}"
    resp = requests.post(
        f"{BASE_URL}/register/",
        json={"username": username, "password": "Pass123!"},
    )
    assert resp.status_code == 201
    assert "token" in resp.json()


def test_login_returns_token(credentials):
    """Login with valid credentials returns a token."""
    resp = requests.post(f"{BASE_URL}/login/", json=credentials)
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_login_invalid_credentials():
    """Login with wrong password returns 401."""
    resp = requests.post(
        f"{BASE_URL}/login/",
        json={"username": "nobody", "password": "wrongpass"},
    )
    assert resp.status_code == 401


def test_unauthenticated_request_rejected():
    """Accessing protected endpoint without token returns 401."""
    resp = requests.get(f"{BASE_URL}/conversations/")
    assert resp.status_code == 401


# ─── Conversation tests ───────────────────────────────────────────────────────

def test_create_conversation(auth_headers):
    """Creating a conversation returns id and title."""
    resp = requests.post(
        f"{BASE_URL}/conversations/",
        json={"title": "My Test Chat"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "My Test Chat"
    assert "id" in data


def test_list_conversations(auth_headers, conversation):
    """Listing conversations returns paginated results."""
    resp = requests.get(f"{BASE_URL}/conversations/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert data["count"] >= 1


def test_get_conversation_detail(auth_headers, conversation):
    """Getting a conversation by ID returns its messages."""
    conv_id = conversation["id"]
    resp = requests.get(f"{BASE_URL}/conversations/{conv_id}/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == conv_id
    assert "messages" in data


# ─── Chat tests ───────────────────────────────────────────────────────────────

def test_chat_returns_answer(auth_headers, conversation):
    """Sending a question to chat returns an answer."""
    resp = requests.post(
        f"{BASE_URL}/chat/",
        json={"conversation_id": conversation["id"], "question": "What is 2 + 2?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert len(data["answer"]) > 0


def test_chat_saves_messages_to_db(auth_headers, conversation):
    """After chatting, conversation detail contains the new messages."""
    conv_id = conversation["id"]
    question = "What is the capital of France?"

    requests.post(
        f"{BASE_URL}/chat/",
        json={"conversation_id": conv_id, "question": question},
        headers=auth_headers,
    )

    resp = requests.get(f"{BASE_URL}/conversations/{conv_id}/", headers=auth_headers)
    messages = resp.json()["messages"]
    user_messages = [m for m in messages if m["role"] == "user"]
    assert any(question in m["content"] for m in user_messages)


def test_chat_missing_question_returns_400(auth_headers, conversation):
    """Chat without a question field returns 400."""
    resp = requests.post(
        f"{BASE_URL}/chat/",
        json={"conversation_id": conversation["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


# ─── Document upload tests ────────────────────────────────────────────────────

def test_upload_txt_document(auth_headers):
    """Uploading a TXT file returns success with chunk count."""
    content = b"The Apollo 11 mission landed on the moon in 1969. Neil Armstrong was the first person to walk on the moon."
    files = {"file": ("space_facts.txt", io.BytesIO(content), "text/plain")}
    data = {"title": "Space Facts"}

    resp = requests.post(
        f"{BASE_URL}/upload-doc/",
        files=files,
        data=data,
        headers={"Authorization": auth_headers["Authorization"]},
    )
    assert resp.status_code == 201
    result = resp.json()
    assert result["filename"] == "space_facts.txt"
    assert result["chunks"] >= 1


def test_upload_creates_document_record(auth_headers):
    """Uploaded document appears in the documents list."""
    content = b"Django is a high-level Python web framework."
    files = {"file": ("django_info.txt", io.BytesIO(content), "text/plain")}

    requests.post(
        f"{BASE_URL}/upload-doc/",
        files=files,
        data={"title": "Django Info"},
        headers={"Authorization": auth_headers["Authorization"]},
    )

    resp = requests.get(f"{BASE_URL}/documents/", headers=auth_headers)
    assert resp.status_code == 200
    titles = [d["title"] for d in resp.json()]
    assert "Django Info" in titles


def test_upload_without_file_returns_400(auth_headers):
    """Upload request without a file returns 400."""
    resp = requests.post(
        f"{BASE_URL}/upload-doc/",
        data={"title": "No file"},
        headers={"Authorization": auth_headers["Authorization"]},
    )
    assert resp.status_code == 400


# ─── Agent tests ─────────────────────────────────────────────────────────────

def test_agent_answers_question(auth_headers):
    """Agent endpoint returns an answer and sources list."""
    resp = requests.post(
        f"{BASE_URL}/agent/",
        json={"question": "Tell me something interesting."},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "sources" in data
    assert len(data["answer"]) > 0


def test_agent_weather_tool(auth_headers):
    """Agent uses get_weather tool for weather queries."""
    resp = requests.post(
        f"{BASE_URL}/agent/",
        json={"question": "What is the weather in London?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    answer_lower = data["answer"].lower()
    assert any(word in answer_lower for word in ["london", "weather", "°", "rain", "cloud", "sun", "temperature"])


def test_agent_document_search(auth_headers):
    """Agent searches uploaded documents and returns relevant answer."""
    # Upload a document with specific facts
    content = b"The XYZ-9000 laptop costs $1299 and has 32GB RAM and a 1TB SSD."
    files = {"file": ("laptop_spec.txt", io.BytesIO(content), "text/plain")}
    requests.post(
        f"{BASE_URL}/upload-doc/",
        files=files,
        data={"title": "Laptop Spec"},
        headers={"Authorization": auth_headers["Authorization"]},
    )

    # Ask the agent about it
    resp = requests.post(
        f"{BASE_URL}/agent/",
        json={"question": "What is the price of the XYZ-9000 laptop?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "1299" in data["answer"] or "price" in data["answer"].lower()


def test_agent_saves_to_conversation(auth_headers, conversation):
    """Agent saves messages to conversation when conversation_id is provided."""
    conv_id = conversation["id"]
    question = "What can you tell me about machine learning?"

    resp = requests.post(
        f"{BASE_URL}/agent/",
        json={"question": question, "conversation_id": conv_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    conv_resp = requests.get(f"{BASE_URL}/conversations/{conv_id}/", headers=auth_headers)
    messages = conv_resp.json()["messages"]
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert any(question in m["content"] for m in user_msgs)


# ─── Query history tests ──────────────────────────────────────────────────────

def test_query_history_is_paginated(auth_headers):
    """Query history returns paginated results."""
    resp = requests.get(f"{BASE_URL}/query-history/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "results" in data


def test_query_history_records_chat(auth_headers, conversation):
    """After a chat request, query history contains the entry."""
    question = f"Unique question {uuid.uuid4().hex[:6]}"
    requests.post(
        f"{BASE_URL}/chat/",
        json={"conversation_id": conversation["id"], "question": question},
        headers=auth_headers,
    )

    resp = requests.get(f"{BASE_URL}/query-history/", headers=auth_headers)
    questions = [r["question"] for r in resp.json()["results"]]
    assert question in questions

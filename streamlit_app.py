import os

import streamlit as st
import requests

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api")


def api_headers():
    return {"Authorization": f"Token {st.session_state.token}"}


def login(username, password):
    resp = requests.post(f"{API_BASE}/login/", json={"username": username, "password": password})
    if resp.status_code == 200:
        return resp.json()["token"]
    return None


def get_conversations():
    resp = requests.get(f"{API_BASE}/conversations/", headers=api_headers())
    if resp.status_code == 200:
        return resp.json().get("results", [])
    return []


def create_conversation(title):
    resp = requests.post(f"{API_BASE}/conversations/", json={"title": title}, headers=api_headers())
    if resp.status_code == 201:
        return resp.json()
    return None


def get_conversation(conv_id):
    resp = requests.get(f"{API_BASE}/conversations/{conv_id}/", headers=api_headers())
    if resp.status_code == 200:
        return resp.json()
    return None


def send_chat(conversation_id, question):
    resp = requests.post(
        f"{API_BASE}/chat/",
        json={"conversation_id": conversation_id, "question": question},
        headers=api_headers(),
    )
    if resp.status_code == 200:
        return resp.json()
    return {"answer": f"Error: {resp.text}"}


def send_agent(question, conversation_id=None):
    payload = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    resp = requests.post(f"{API_BASE}/agent/", json=payload, headers=api_headers())
    if resp.status_code == 200:
        return resp.json()
    return {"answer": f"Error: {resp.text}", "sources": []}


def upload_document(file, title):
    files = {"file": (file.name, file.getvalue(), file.type)}
    data = {"title": title}
    resp = requests.post(
        f"{API_BASE}/upload-doc/",
        files=files,
        data=data,
        headers=api_headers(),
    )
    return resp.json(), resp.status_code


# ─── Session state defaults ───────────────────────────────────────────────────
if "token" not in st.session_state:
    st.session_state.token = None
if "active_conv_id" not in st.session_state:
    st.session_state.active_conv_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# ─── Login screen ─────────────────────────────────────────────────────────────
if not st.session_state.token:
    st.title("GenAI Assistant")
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        token = login(username, password)
        if token:
            st.session_state.token = token
            st.rerun()
        else:
            st.error("Invalid credentials")
    st.stop()

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("GenAI Assistant")

    if st.button("Logout"):
        st.session_state.token = None
        st.session_state.active_conv_id = None
        st.session_state.messages = []
        st.rerun()

    st.divider()

    # Create new conversation
    st.subheader("Conversations")
    new_title = st.text_input("New conversation title", placeholder="e.g. Python help")
    if st.button("Create"):
        if new_title.strip():
            conv = create_conversation(new_title.strip())
            if conv:
                st.session_state.active_conv_id = conv["id"]
                st.session_state.messages = []
                st.rerun()

    # List existing conversations
    conversations = get_conversations()
    for conv in conversations:
        label = f"{conv['title']}"
        if st.button(label, key=f"conv_{conv['id']}"):
            st.session_state.active_conv_id = conv["id"]
            # Load message history
            data = get_conversation(conv["id"])
            st.session_state.messages = data.get("messages", []) if data else []
            st.rerun()

    st.divider()

    # Document upload
    st.subheader("Upload Document")
    uploaded_file = st.file_uploader("Choose a PDF or TXT file", type=["pdf", "txt"])
    doc_title = st.text_input("Document title", placeholder="Optional title")
    if st.button("Upload"):
        if uploaded_file:
            with st.spinner("Uploading and indexing..."):
                result, code = upload_document(uploaded_file, doc_title or uploaded_file.name)
            if code == 201:
                st.success(f"Uploaded! {result['chunks']} chunks indexed.")
            else:
                st.error(f"Upload failed: {result}")
        else:
            st.warning("Please select a file first.")

# ─── Main chat area ───────────────────────────────────────────────────────────
st.title("Chat")

if not st.session_state.active_conv_id:
    st.info("Create or select a conversation from the sidebar to start chatting.")
    st.stop()

# Mode toggle
mode = st.radio("Mode", ["Chat (with memory)", "Agent (weather + documents)"], horizontal=True)

# Display messages
for msg in st.session_state.messages:
    role = msg["role"] if isinstance(msg, dict) else msg.role
    content = msg["content"] if isinstance(msg, dict) else msg.content
    with st.chat_message(role):
        st.write(content)

# Chat input
if prompt := st.chat_input("Type your message..."):
    # Show user message immediately
    with st.chat_message("user"):
        st.write(prompt)

    with st.spinner("Thinking..."):
        if mode == "Chat (with memory)":
            result = send_chat(st.session_state.active_conv_id, prompt)
            answer = result.get("answer", "")
            sources = []
        else:
            result = send_agent(prompt, st.session_state.active_conv_id)
            answer = result.get("answer", "")
            sources = result.get("sources", [])

    # Show assistant response
    with st.chat_message("assistant"):
        st.write(answer)
        if sources:
            st.caption(f"Sources: {', '.join(sources)}")

    # Update local message list
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.messages.append({"role": "assistant", "content": answer})

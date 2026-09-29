"""Minimal FastAPI proxy for a deployed A2A agent (Agent Runtime, agents-cli 1.1.0+).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over the A2A protocol, returning replies as
structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.
"""

import os
import uuid

import google.auth
import google.auth.transport.requests
from google.protobuf.json_format import MessageToDict
import httpx

try:
    from a2a.client import ClientConfig, create_client
    from a2a.types import Message, Part, Role, SendMessageRequest
    from a2a.utils.constants import PROTOCOL_VERSION_1_0, VERSION_HEADER, TransportProtocol
    USE_A2A_V1 = True
except ImportError:
    from a2a.compat.v0_3.types import (
        AgentCard,
        FilePart,
        Message,
        Part,
        Role,
        TaskArtifactUpdateEvent,
        TextPart,
        TransportProtocol,
    )
    from a2a.client import ClientConfig, ClientFactory
    USE_A2A_V1 = False

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

RESOURCE = os.environ.get(
    "AGENT_ENGINE_RESOURCE_NAME",
    "projects/762001249959/locations/us-central1/reasoningEngines/3952409500564062208",
)
# The agent's app directory (matches agent_directory in agents-cli-manifest.yaml).
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
# Location is embedded in the resource name: projects/<p>/locations/<loc>/reasoningEngines/<id>.
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

# A2A endpoint for an Agent Runtime deployment, via the Agent Engine HTTP passthrough.
A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)

# The agent tags its A2UI data parts with this mime type.
_A2UI_MIME = "application/json+a2ui"

# One set of ADC credentials, refreshed per request (access tokens expire ~1h).
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    headers = {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }
    if USE_A2A_V1:
        headers[VERSION_HEADER] = PROTOCOL_VERSION_1_0
    return headers


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# Reuse ONE A2A context per user so the agent remembers the conversation.
_contexts: dict[str, str] = {}


def _extract_single_part(p) -> dict | None:
    if getattr(p, "text", None):
        return {"kind": "text", "text": p.text}
    if getattr(p, "url", None):
        return {"kind": "text", "text": p.url}
    if hasattr(p, "HasField") and p.HasField("data"):
        data_dict = MessageToDict(p.data)
        meta = data_dict.get("metadata") or {}
        if meta.get("mimeType") == _A2UI_MIME:
            return {"kind": "a2ui", "data": data_dict.get("data", data_dict)}
        return {"kind": "a2ui", "data": data_dict}
    root = getattr(p, "root", p)
    if hasattr(root, "text") and root.text:
        return {"kind": "text", "text": root.text}
    if hasattr(root, "data") and root.data is not None:
        meta = getattr(root, "metadata", None) or {}
        mime = meta.get("mimeType") if isinstance(meta, dict) else None
        if mime == _A2UI_MIME:
            return {"kind": "a2ui", "data": root.data}
    return None


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        if USE_A2A_V1:
            config = ClientConfig(
                httpx_client=client,
                supported_protocol_bindings=[
                    TransportProtocol.JSONRPC,
                    TransportProtocol.HTTP_JSON,
                ],
            )
            a2a_client = await create_client(A2A_BASE, config)
            msg = Message(
                message_id=str(uuid.uuid4()),
                role=Role.ROLE_USER,
                parts=[Part(text=message)],
                context_id=_contexts.get(user_id, ""),
            )
            async for chunk in a2a_client.send_message(SendMessageRequest(message=msg)):
                if chunk.HasField("artifact_update"):
                    if chunk.artifact_update.context_id:
                        _contexts[user_id] = chunk.artifact_update.context_id
                    for p in chunk.artifact_update.artifact.parts:
                        ext = _extract_single_part(p)
                        if ext:
                            parts.append(ext)
                elif chunk.HasField("task"):
                    if chunk.task.context_id:
                        _contexts[user_id] = chunk.task.context_id
                    for artifact in chunk.task.artifacts:
                        for p in artifact.parts:
                            ext = _extract_single_part(p)
                            if ext:
                                parts.append(ext)
                elif chunk.HasField("message"):
                    for p in chunk.message.parts:
                        ext = _extract_single_part(p)
                        if ext:
                            parts.append(ext)
        else:
            # Fallback path for v0.3
            card_resp = await client.get(f"{A2A_BASE}/.well-known/agent-card.json")
            card_resp.raise_for_status()
            card = AgentCard(**card_resp.json())
            card.url = A2A_BASE
            factory = ClientFactory(
                ClientConfig(
                    supported_transports=[
                        TransportProtocol.jsonrpc,
                        TransportProtocol.http_json,
                    ],
                    httpx_client=client,
                )
            )
            a2a_client = factory.create(card)
            msg = Message(
                message_id=str(uuid.uuid4()),
                role=Role.user,
                parts=[Part(root=TextPart(text=message))],
                context_id=_contexts.get(user_id),
            )
            async for event in a2a_client.send_message(msg):
                if not isinstance(event, tuple):
                    continue
                task, update = event
                if task is not None and getattr(task, "context_id", None):
                    _contexts[user_id] = task.context_id
                if isinstance(update, TaskArtifactUpdateEvent):
                    for p in update.artifact.parts:
                        ext = _extract_single_part(p)
                        if ext:
                            parts.append(ext)

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


# Serve the chat UI (keep this mount last so /chat wins).
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

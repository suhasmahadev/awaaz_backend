# Current Project Status: Minimal Chat Skeleton

This document describes the current stripped-down state of the project. It has been strictly cleaned of previous domain logic (academic/college modules) and now serves as a clean starting point for the AWAAZ-PROOF hackathon build.

## 1. Tech Stack Overview
*   **Backend:** Python, FastAPI, Google ADK (`uvicorn`).
*   **Frontend:** React, Vite.
*   **LLM Engine:** `gemini-2.5-flash` natively integrated via Google ADK.

## 2. Directory & Infrastructure State
*   `backend/main.py`: A sterile FastAPI entry point. It has an empty `lifespan` block (ready for new DB bootstrapping) and only mounts the 4 core routers below.
*   **Deleted Code:** All domain-specific code, services, repositories, schemas, and models have been wiped out.
*   **Missing Critical Infra (Action Required):** During the previous domain cleanup, the database singleton (`db.py`) and the JWT auth layer (`auth_security.py`, `auth_models.py`) were deleted. The next LLM step must recreate them based on the new SPEC.

## 3. Active Backend Endpoints
Currently, the backend has only these 4 functional components:

| Endpoint | Path | Status |
| :--- | :--- | :--- |
| **Agent Chat** | `POST /agent/chat` | **Active**. Clean pass-through to Google ADK. No tools or custom pipelines attached. |
| **File Upload** | `POST /academic/api/files/process-file` | **Active**. Parses PDFs, CSVs, Excels to text/base64 for the LLM. |
| **Voice Processing** | `POST /academic/api/voice/speech-to-text` | **Active**. Acts as a functional placeholder for audio parsing. |
| **Authentication** | `POST /auth/login` | **Mocked**. Currently hardcoded to return dummy JWTs to keep the frontend running. Needs to be rewritten to support the new `asyncpg` DB. |

## 4. Agent Configuration (`backend/agent/`)
*   `agent.py`: Exposes `root_agent = LlmAgent(...)` using Gemini, a generic prompt, and an empty tool list (`tools=[]`).
*   **Prompt & Tool Files**: Filenames like `tools.py`, `admin_prompt.py`, and `student_prompt.py` were retained per constraints, but their contents have been completely cleared. They are blank slates ready for new domain tools.

## 5. Frontend State (`frontend/`)
*   **Pages:** All landing pages, dashboards, and login screens were deleted.
*   **UI:** The frontend now exclusively and immediately renders `ChatPage.jsx` at the root path (`/`). There is no routing wrapper.
*   **Functionality:** The Chat UI, file attachment handling, and ADK Server-Sent Events (SSE) streaming remain fully intact and operational.

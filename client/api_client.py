"""httpx wrapper + UDP LAN server auto-discovery listener."""

from __future__ import annotations

import threading
from typing import Optional, Callable

import httpx

from server.udp_broadcaster import listen_for_server


class APIClient:
    """HTTP client for communicating with the LAN quiz server."""

    def __init__(self, base_url: str = ""):
        self._base_url = base_url
        self._token: str | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, url: str):
        self._base_url = url.rstrip("/")

    def set_token(self, token: str):
        """Set the JWT auth token."""
        self._token = token

    def clear_token(self):
        """Clear the auth token."""
        self._token = None

    def _headers(self) -> dict:
        """Build request headers with optional auth."""
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self._base_url, timeout=15.0)

    # ── Generic HTTP Methods ─────────────────────────────────────────────

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        with self._client() as client:
            return client.get(path, headers=self._headers(), params=params)

    def post(self, path: str, json: dict | None = None) -> httpx.Response:
        with self._client() as client:
            return client.post(path, headers=self._headers(), json=json)

    def patch(self, path: str, json: dict | None = None) -> httpx.Response:
        with self._client() as client:
            return client.patch(path, headers=self._headers(), json=json)

    def delete(self, path: str) -> httpx.Response:
        with self._client() as client:
            return client.delete(path, headers=self._headers())

    # ── Auth Endpoints ───────────────────────────────────────────────────

    def register(self, data: dict) -> dict:
        resp = self.post("/auth/register", json=data)
        resp.raise_for_status()
        result = resp.json()
        self.set_token(result["access_token"])
        return result

    def login(self, email: str, password: str) -> dict:
        resp = self.post("/auth/login", json={"email": email, "password": password})
        resp.raise_for_status()
        result = resp.json()
        self.set_token(result["access_token"])
        return result

    # ── Quiz Endpoints ───────────────────────────────────────────────────

    def list_quizzes(self, active_only: bool = False) -> list[dict]:
        params = {"active_only": str(active_only).lower()} if active_only else None
        resp = self.get("/quizzes/", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_quiz(self, quiz_id: int) -> dict:
        resp = self.get(f"/quizzes/{quiz_id}")
        resp.raise_for_status()
        return resp.json()

    def create_quiz(self, data: dict) -> dict:
        resp = self.post("/quizzes/", json=data)
        resp.raise_for_status()
        return resp.json()

    def toggle_quiz(self, quiz_id: int, is_active: bool) -> dict:
        resp = self.patch(f"/quizzes/{quiz_id}/toggle", json={"is_active": is_active})
        resp.raise_for_status()
        return resp.json()

    def delete_quiz(self, quiz_id: int) -> dict:
        resp = self.delete(f"/quizzes/{quiz_id}")
        resp.raise_for_status()
        return resp.json()

    # ── Attempt Endpoints ────────────────────────────────────────────────

    def start_attempt(self, quiz_id: int) -> dict:
        resp = self.post(f"/attempts/start/{quiz_id}")
        resp.raise_for_status()
        return resp.json()

    def save_draft(self, attempt_id: int, answers: list[dict]) -> dict:
        resp = self.post(f"/attempts/draft/{attempt_id}", json={"answers": answers})
        resp.raise_for_status()
        return resp.json()

    def submit_attempt(self, attempt_id: int, answers: list[dict]) -> dict:
        resp = self.post(f"/attempts/submit/{attempt_id}", json={"answers": answers})
        resp.raise_for_status()
        return resp.json()

    def my_attempts(self) -> list[dict]:
        resp = self.get("/attempts/my")
        resp.raise_for_status()
        return resp.json()

    # ── Grading Endpoints ────────────────────────────────────────────────

    def get_pending_reviews(self) -> list[dict]:
        resp = self.get("/grading/pending")
        resp.raise_for_status()
        return resp.json()

    def grade_answers(self, grades: list[dict]) -> dict:
        resp = self.post("/grading/grade", json={"grades": grades})
        resp.raise_for_status()
        return resp.json()

    def list_all_attempts(self, quiz_id: int | None = None) -> list[dict]:
        params = {"quiz_id": quiz_id} if quiz_id else None
        resp = self.get("/grading/attempts", params=params)
        resp.raise_for_status()
        return resp.json()

    def export_gradebook(self) -> dict:
        resp = self.post("/grading/export-excel")
        resp.raise_for_status()
        return resp.json()

    # ── Health ───────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        try:
            resp = self.get("/health")
            return resp.status_code == 200
        except Exception:
            return False


def discover_server_async(callback: Callable[[dict | None], None]):
    """Discover server in a background thread and call back with result."""
    def _worker():
        result = listen_for_server()
        callback(result)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t

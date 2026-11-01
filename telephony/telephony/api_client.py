"""The backend calls the telephony service makes: starting, logging and ending calls."""

from __future__ import annotations

from typing import Any

import httpx

from telephony.config import get_settings
from telephony.logging_setup import get_logger

log = get_logger("api_client")


class BackendClient:
    """Async HTTP client for the MedNexa backend.

    Use as an async context manager or call ``aclose()`` when done.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        settings = get_settings()
        self._base = (base_url or settings.backend_url).rstrip("/")
        headers = {"Content-Type": "application/json"}
        if settings.backend_api_key:
            headers["Authorization"] = f"Bearer {settings.backend_api_key}"
        self._client = httpx.AsyncClient(base_url=self._base, timeout=timeout, headers=headers)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> BackendClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"/api/v1{path}"
        resp = await self._client.post(url, json=body)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def start_call(self, hospital_id: str, caller_phone: str) -> str:
        """Returns the new call session's id."""
        data = await self._post(
            "/calls",
            {"hospital_id": hospital_id, "caller_phone": caller_phone},
        )
        session_id: str = data["id"]
        log.info("call_started", session_id=session_id, caller_phone=caller_phone)
        return session_id

    async def append_log(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_called: str | None = None,
        tool_result: str | None = None,
        appointment_id: str | None = None,
    ) -> None:
        """``role`` is USER, ASSISTANT, TOOL or SYSTEM."""
        body: dict[str, Any] = {"role": role.upper(), "content": content}
        if tool_called:
            body["tool_called"] = tool_called
        if tool_result:
            body["tool_result"] = tool_result
        if appointment_id:
            body["appointment_id"] = appointment_id
        try:
            await self._post(f"/calls/{session_id}/logs", body)
        except Exception as exc:
            # A transcript line that can't be saved must not end the call.
            log.warning("append_log_failed", session_id=session_id, error=str(exc))

    async def end_call(
        self,
        session_id: str,
        *,
        outcome: str = "OTHER",
        summary: str | None = None,
        language_detected: str | None = None,
        escalated_to_human: bool = False,
    ) -> None:
        """``outcome`` is BOOKED, CANCELLED, RESCHEDULED, INFO_PROVIDED, ESCALATED,
        ABANDONED or OTHER."""
        body: dict[str, Any] = {
            "call_outcome": outcome,
            "escalated_to_human": escalated_to_human,
        }
        if summary:
            body["summary"] = summary
        if language_detected:
            body["language_detected"] = language_detected
        try:
            await self._post(f"/calls/{session_id}/end", body)
            log.info("call_ended", session_id=session_id, outcome=outcome)
        except Exception as exc:
            log.warning("end_call_failed", session_id=session_id, error=str(exc))

    async def health_check(self) -> bool:
        """Return True if the backend is reachable and healthy."""
        try:
            resp = await self._client.get("/api/v1/health")
            return resp.status_code == 200
        except Exception:
            return False

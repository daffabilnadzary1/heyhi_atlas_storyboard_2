"""
app/clients/video_kieai_client.py

TESTING-ONLY, opt-in kie.ai video provider (video_provider="kieai"). The default
gemini path (GeminiVeoClient) is untouched. Isolated so it is trivial to delete:
remove this file + the "kieai" entry in app/pipeline/video_providers.py.

Implements the shared VeoClient Protocol (VeoJobSpec -> mp4 bytes) so routing,
retry, cost-logging and scene_gen are identical to the Gemini path — ONLY the
provider call differs. The request/response/auth contract mirrors
bench/test_video_kieai.py (the source of truth for kie.ai).

*** LIVE CALLS CONSUME kie.ai CREDITS and EGRESS PROJECT FRAMES TO A THIRD-PARTY
HOST — human review before running. See change_kieai.md / Human Review Flag. ***
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import requests

from dotenv import load_dotenv

from app.clients.video_veo_client import (
    TransientVeoError,
    VeoClient,          # noqa: F401  (documents the Protocol this class satisfies)
    VeoError,
    VeoJobSpec,
    snap_duration,
)
from app.utils.retry import looks_transient

load_dotenv()

BASE_URL = "https://api.kie.ai"
UPLOAD_ENDPOINT = "https://kieai.redpandaai.co/api/file-stream-upload"

# spec.task -> kie generationType
_GEN_TYPE = {
    "reference-to-video": "REFERENCE_2_VIDEO",          # references as imageUrls (Fast/Lite only)
    "image-to-video": "FIRST_AND_LAST_FRAMES_2_VIDEO",  # single seed frame = animate-from
}
# spec.model -> kie model (both verified).
_MODEL_IDS = {"Veo 3.1 Fast": "veo3_fast", "Veo 3.1 Lite": "veo3_lite"}


class KieAiVeoClient:
    """VeoClient over kie.ai. Reads KIE_API_KEY at construction and nowhere else;
    the key is never printed or persisted (mirrors config.make_client)."""

    def __init__(self, api_key_env: str = "KIE_API_KEY",
                 poll_s: float = 30.0, timeout_s: float = 900.0):
        key = os.environ.get(api_key_env)
        if not key:
            raise RuntimeError(f"{api_key_env} not set in environment")
        self._auth = {"Authorization": f"Bearer {key}"}
        self.poll_s = poll_s
        self.timeout_s = timeout_s

    # -- one requests call; 5xx/timeout -> TransientVeoError so retry backs off --
    def _req(self, method: str, url: str, **kw) -> requests.Response:
        headers = {**self._auth, **kw.pop("headers", {})}
        try:
            r = requests.request(method, url, headers=headers, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if (code and 500 <= code < 600) or looks_transient(e):
                raise TransientVeoError(str(e)) from e
            raise VeoError(str(e)) from e

    # -- bytes -> temp file -> kie host URL (kie fetches the URL server-side) --
    def _upload(self, data: bytes) -> str:
        fd, name = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        tmp = Path(name)
        try:
            tmp.write_bytes(data)
            with tmp.open("rb") as f:
                r = self._req(
                    "post", UPLOAD_ENDPOINT,
                    files={"file": (tmp.name, f)},
                    data={"uploadPath": "veo-inputs"},
                    timeout=120,
                )
        finally:
            tmp.unlink(missing_ok=True)
        url = (r.json().get("data") or {}).get("downloadUrl")
        if not url:
            raise VeoError(f"kie upload returned no downloadUrl: {r.text}")
        return url

    def credits(self):
        """Account's remaining kie credit balance (for scene_gen's before/after
        cost log). Mirrors test_video_kieai.get_credits."""
        return self._req("get", f"{BASE_URL}/api/v1/chat/credit", timeout=30).json().get("data")

    def _image_urls(self, spec: VeoJobSpec) -> list[str]:
        blobs = spec.references if spec.references else ([spec.image] if spec.image else [])
        return [self._upload(b) for b in blobs]

    def generate(self, spec: VeoJobSpec) -> bytes:
        gen_type = _GEN_TYPE.get(spec.task)
        model = _MODEL_IDS.get(spec.model)
        if not gen_type:
            raise VeoError(f"kie: unsupported task '{spec.task}'")
        if not model:
            raise VeoError(f"kie: unknown model '{spec.model}'")

        payload: dict = {
            "prompt": spec.prompt,
            "model": model,
            "aspect_ratio": spec.aspect_ratio,
            "generationType": gen_type,
            "enableTranslation": True,
            "enableFallback": False,          # refuse silent 720p downgrade
        }
        if spec.duration_s:
            payload["duration"] = int(snap_duration(spec.duration_s))
        urls = self._image_urls(spec)         # uploads happen here (egress)
        if urls:
            payload["imageUrls"] = urls

        r = self._req(
            "post", f"{BASE_URL}/api/v1/veo/generate",
            headers={"Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        task_id = (r.json().get("data") or {}).get("taskId")
        if not task_id:
            raise VeoError(f"kie: no taskId returned: {r.text}")

        record = self._poll(task_id)
        result_urls = (record.get("response") or {}).get("resultUrls") or []
        if not result_urls:
            raise VeoError(f"kie: task {task_id} finished with no resultUrls")
        # result URLs are temporary (~14 days) — download to bytes now.
        return self._req("get", result_urls[0], timeout=180).content

    def _poll(self, task_id: str) -> dict:
        # successFlag: 0 generating | 1 success | 2 failed | 3 gen failed
        waited = 0.0
        while waited < self.timeout_s:
            r = self._req(
                "get", f"{BASE_URL}/api/v1/veo/record-info",
                params={"taskId": task_id}, timeout=30,
            )
            data = r.json().get("data") or {}
            flag = data.get("successFlag")
            if flag == 1:
                return data
            if flag in (2, 3):
                raise VeoError(f"kie: task {task_id} failed (successFlag={flag})")
            time.sleep(self.poll_s)
            waited += self.poll_s
        raise TransientVeoError(f"kie: task {task_id} poll timeout after {self.timeout_s}s")
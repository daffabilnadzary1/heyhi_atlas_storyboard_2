"""
kie.ai Nano Banana (Google Gemini 2.5 Flash Image) — test script.

Text-to-image and image editing via kie.ai's unified Market "jobs" API.
NOTE: this is a DIFFERENT endpoint and payload shape than the Veo script —
params live inside a nested `input` object, and you poll a different URL.

Edit the CONFIG block below, then run:
    export KIE_API_KEY="your_key_here"     # get one at https://kie.ai/api-key
    python kie_nano_banana_test.py

Output goes to _storage/kie.ai/run_<RUN_ID>/ (record.json + the image[s]).

=============================================================================
JOB TYPES  ->  model
=============================================================================
  generate   google/nano-banana        text-to-image, no input images.
  edit       google/nano-banana-edit   edits/composites from IMAGE_URLS
                                        (up to 10 input images).

  Related models on the same jobs API if you want more: google/nano-banana-pro
  (Gemini 3 Pro Image, 4K), nano-banana-2 (Gemini 3.1 Flash Image).

=============================================================================
PARAMETERS — POST https://api.kie.ai/api/v1/jobs/createTask  (JSON body)
=============================================================================
  model         str   "google/nano-banana" | "google/nano-banana-edit".
  callBackUrl   str   optional webhook; results POSTed here on completion.
  input         obj   model-specific, nested:
      prompt        str   (required) what to generate / how to edit.
      image_urls    list  edit only: input image URL(s), up to 10.
      output_format str   "png" | "jpeg".
      aspect_ratio  str   e.g. "1:1", "3:2", "2:3", "16:9", "9:16", "auto".
                          (Confirm the ratio set on the model's doc page.)

=============================================================================
RETURN FORMAT
=============================================================================
  Submit  -> {"code":200,"msg":"success","data":{"taskId":"task_..."}}
             HTTP 200 means CREATED, not finished (generation is async).

  GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=...  -> data:
      state            "waiting" | "queuing" | "generating" | "success" | "fail"
      resultJson       JSON *string*; parse it -> {"resultUrls": ["...png"]}
      param            your original request, echoed as a string
      failCode/failMsg failure detail when state == "fail"
      creditsConsumed  credits this task used  <-- per-task cost, unlike Veo
      costTime/createTime/completeTime/progress
  Generated image URLs typically expire after ~24 hours — download promptly.

=============================================================================
CREDIT COST
=============================================================================
  This API DOES return a per-task cost: data.creditsConsumed. The script
  prints it, and also diffs the account balance
  (GET https://api.kie.ai/api/v1/chat/credit) as a cross-check.
  Rates: https://kie.ai/billing ; per-task log: https://kie.ai/logs.
  Failed tasks are not charged; new accounts get 80 free credits.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# ============================ CONFIG — edit these ============================
JOB = "generate"                    # "generate" | "edit"

PROMPT = ("""
Make the referenced attached image a male version, with the same art style""")

# edit only: 1–10 input image URLs. Leave empty [] for "generate".
IMAGE_URLS = []

OUTPUT_FORMAT = "png"               # "png" | "jpeg"
ASPECT_RATIO = "1:1"                # "1:1" | "3:2" | "2:3" | "16:9" | "9:16" | "auto"

RUN_ID = "run_vox_motion"                       # set manually per run; output goes to
                                    # _storage/kie.ai/run_<RUN_ID>/. Bump this
                                    # each run — an existing run is not clobbered.

ALLOW_EXISTING_RUN = True
# ===========================================================================

BASE_URL = "https://api.kie.ai"
API_KEY = os.environ.get("KIE_API_KEY")

if not API_KEY:
    sys.exit("Set KIE_API_KEY first:  export KIE_API_KEY='your_key'")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# Output root, relative to this script so it's the same wherever you run from.
STORAGE_ROOT = Path(__file__).resolve().parent / "_storage" / "kie.ai"

# job name -> (model, needs images, min/max images)
JOBS = {
    "generate": ("google/nano-banana", 0, 0),
    "edit":     ("google/nano-banana-edit", 1, 10),
}


def get_credits():
    """Return the account's remaining credit balance (or None on failure)."""
    r = requests.get(f"{BASE_URL}/api/v1/chat/credit", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("data")


def submit_image(model, prompt, output_format, aspect_ratio, image_urls=None):
    """Submit a jobs/createTask request. Returns the taskId."""
    task_input = {
        "prompt": prompt,
        "output_format": output_format,
        "aspect_ratio": aspect_ratio,
    }
    if image_urls:
        task_input["image_urls"] = image_urls

    payload = {"model": model, "input": task_input}

    r = requests.post(f"{BASE_URL}/api/v1/jobs/createTask",
                      headers=HEADERS, json=payload, timeout=30)
    print("\n--- submit response ---")
    print(r.status_code, r.text)
    r.raise_for_status()

    task_id = (r.json().get("data") or {}).get("taskId")
    if not task_id:
        raise RuntimeError(f"No taskId returned: {r.text}")
    return task_id


def poll_image(task_id, interval=3, timeout=900):
    """Poll jobs/recordInfo until the task finishes. Returns the final record."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/v1/jobs/recordInfo",
                         headers=HEADERS, params={"taskId": task_id}, timeout=30)
        r.raise_for_status()
        data = r.json().get("data") or {}
        state = data.get("state")

        if state == "success":
            print("\n--- final record (success) ---")
            print(r.text)
            return data
        if state == "fail":
            print("\n--- final record (fail) ---")
            print(r.text)
            return data

        print(f"state={state} progress={data.get('progress')}… waiting {interval}s")
        time.sleep(interval)

    raise TimeoutError(f"Task {task_id} did not finish within {timeout}s")


def result_urls(record):
    """resultJson is a JSON *string* — parse it and pull resultUrls."""
    raw = record.get("resultJson")
    if not raw:
        return []
    try:
        return (json.loads(raw) or {}).get("resultUrls") or []
    except (json.JSONDecodeError, TypeError):
        return []


def validate():
    """Fail fast on documented constraints, before spending a call."""
    if JOB not in JOBS:
        sys.exit(f"JOB must be one of {list(JOBS)}; got '{JOB}'.")
    model, min_imgs, max_imgs = JOBS[JOB]
    n = len(IMAGE_URLS)
    if n < min_imgs:
        sys.exit(f"'{JOB}' needs at least {min_imgs} image URL(s); got {n}.")
    if n > max_imgs:
        sys.exit(f"'{JOB}' accepts at most {max_imgs} image URL(s); got {n}.")
    if JOB == "generate" and n:
        sys.exit("'generate' takes no images — empty IMAGE_URLS.")

    run_dir = STORAGE_ROOT / f"run_{RUN_ID}"
    if run_dir.exists() and any(run_dir.iterdir()) and not ALLOW_EXISTING_RUN:
        sys.exit(f"{run_dir} already has files — set ALLOW_EXISTING_RUN or bump RUN_ID.")
    return model


def save_run(run_id, record):
    """Write the run metadata and download the result image(s). Returns paths."""
    run_dir = STORAGE_ROOT / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "record.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    urls = result_urls(record)
    ext = "jpg" if OUTPUT_FORMAT.lower() in ("jpg", "jpeg") else "png"
    saved = []
    for i, url in enumerate(urls):
        name = f"image.{ext}" if len(urls) == 1 else f"image_{i}.{ext}"
        dest = run_dir / name
        resp = requests.get(url, timeout=180)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        saved.append(dest)
    return run_dir, saved


def main():
    model = validate()

    before = get_credits()
    print(f"Credits before: {before}")

    task_id = submit_image(
        model=model,
        prompt=PROMPT,
        output_format=OUTPUT_FORMAT,
        aspect_ratio=ASPECT_RATIO,
        image_urls=IMAGE_URLS or None,
    )
    print(f"\ntaskId: {task_id}")

    record = poll_image(task_id)

    run_dir, saved = save_run(RUN_ID, record)
    print(f"\nSaved run to: {run_dir}")
    print("  record.json")
    for path in saved:
        print(f"  {path.name}")
    if not saved:
        print("  (no result images — check record.json for the failure reason)")

    # Per-task cost is reported by this API directly; balance diff cross-checks it.
    print(f"\ncreditsConsumed (from record): {record.get('creditsConsumed')}")
    after = get_credits()
    print(f"Credits before/after: {before} -> {after}")
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        print(f"Balance delta: {before - after}")


if __name__ == "__main__":
    main()
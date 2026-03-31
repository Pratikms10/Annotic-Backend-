import requests
import json
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE_URL = "https://backend.annotic.in"
TASK_ID = 105008
ANNOTATION_ID = 183370

TOKEN = "JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwjoxNzgyODg2NTM3LCJqdGkiOiJjMjhmZjM3ODBiY2U0YzdlOTA2ZmVmN2EyMmY1ZjEwZiIsInVzZXJfaWQiOjI2MDh9._Niwm9MswKy90lt3PD8h-KYCt8VQyJnpoIDSVKYBhrc"

INPUT_JSON = r"D:\pratik\pratikms10\yt\durga soft\audio__3__annotation.json"
# ──────────────────────────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    "Authorization":"JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzgyODg2NTM3LCJqdGkiOiJjMjhmZjM3ODBiY2U0YzdlOTA2ZmVmN2EyMmY1ZjEwZiIsInVzZXJfaWQiOjI2MDh9._Niwm9MswKy90lt3PD8h-KYCt8VQyJnpoIDSVKYBhrc",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://annotic.in",
    "Referer": "https://annotic.in/",
})


def normalize_time(t: str) -> str:
    t = t.strip()
    for fmt in ("%H:%M:%S.%f", "%M:%S.%f"):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
        except ValueError:
            pass
    raise ValueError(f"Unsupported time format: {t}")

def build_result_from_json(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "annotations" not in data or not isinstance(data["annotations"], list):
        raise ValueError("Invalid JSON: 'annotations' list not found")

    result = []
    for idx, seg in enumerate(data["annotations"], start=1):
        if "Transcription" not in seg or "start" not in seg or "end" not in seg:
            raise ValueError(f"Invalid segment at index {idx}: missing required keys")

        text = " ".join(seg["Transcription"]).strip()

        result.append({
            "id": idx,
            "text": text,
            "start_time": normalize_time(seg["start"]),
            "end_time": normalize_time(seg["end"]),
            "speaker_id": "Speaker 0"
        })

    return result

def get_annotations():
    url = f"{BASE_URL}/task/{TASK_ID}/annotations/?enable_chitralekha_UI=true"
    r = session.get(url, timeout=30)

    print("\nGET URL:", url)
    print("GET status code:", r.status_code)
    print("GET content-type:", r.headers.get("Content-Type"))
    print("GET raw response preview:")
    print(r.text[:2000])

    r.raise_for_status()
    return r.json()

def patch_annotation(new_result: list):
    payload = {
        "id": ANNOTATION_ID,
        "task_id": TASK_ID,
        "task": TASK_ID,
        "result": new_result,
        "annotation_status": "labeled"
    }

    url = f"{BASE_URL}/annotation/{ANNOTATION_ID}/"
    r = session.patch(
        url,
        params={"enable_chitralekha_UI": "true"},
        json=payload,
        timeout=30,
    )

    print("\nPATCH URL:", r.url)
    print("HTTP Status Code:", r.status_code)
    print("Response Text:")
    print(r.text)

    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    try:
        print("── Reading input JSON...")
        new_result = build_result_from_json(INPUT_JSON)
        print(f"   {len(new_result)} segments loaded")

        print("\n   Preview of first 3 segments:")
        for seg in new_result[:3]:
            print(f"   [{seg['start_time']} -> {seg['end_time']}] {seg['text'][:80]}")

        print("\n── Fetching current state from server...")
        annotations = get_annotations()

        if not isinstance(annotations, list) or not annotations:
            raise ValueError("No annotations returned from server")

        target = None
        for ann in annotations:
            if ann.get("id") == ANNOTATION_ID:
                target = ann
                break

        if target is None:
            raise ValueError(f"Annotation ID {ANNOTATION_ID} not found for task {TASK_ID}")

        current_segments = target.get("result", [])
        print(f"\n   Segments on server : {len(current_segments)}")
        print(f"   Status             : {target.get('annotation_status')}")
        print(f"   Annotation ID      : {target.get('id')}")

        confirm = input("\n   Proceed with PATCH? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("   Aborted")
            raise SystemExit

        print("\n── Sending PATCH...")
        response = patch_annotation(new_result)

        print("\n✓ SUCCESS")
        print("Annotation ID :", response.get("id"))
        print("Status        :", response.get("annotation_status"))
        print("Updated At    :", response.get("updated_at"))
        print("Segments Saved:", len(response.get("result", [])))

    except requests.HTTPError as e:
        print("\n✗ PATCH failed")
        if e.response is not None:
            print("Status :", e.response.status_code)
            print("Body   :", e.response.text)
        raise

    except Exception as e:
        print("\n✗ ERROR")
        print(str(e))
        raise



"""End-to-end DRM checks against live containers (http://localhost:8000)."""
import urllib.request
import urllib.error
import json

BASE = "http://localhost:8000"


def _post(path, body=None, token=None):
    data = json.dumps(body).encode() if body else b""
    req = urllib.request.Request(f"{BASE}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read()) if r.status != 204 else None


def _get(path, token=None):
    req = urllib.request.Request(f"{BASE}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _login(email, password):
    _, data = _post("/api/auth/login", {"email": email, "password": password})
    return data["access_token"]


def main():
    # 1. Login as creator
    creator = _login("creator@mytube.local", "Creator@123")
    print("[ok] creator logged in")

    # 2. Get upload URL (to get a video_id for testing)
    _, url_data = _post("/api/upload-url",
                        {"filename": "test.mp4", "size": 1024}, creator)
    vid = url_data["video_id"]
    print(f"[ok] upload-url issued for {vid}")

    # 3. Key endpoint with no auth -> 401
    status, _ = _get(f"/api/keys/{vid}")
    assert status == 401, f"expected 401, got {status}"
    print("[ok] unauthenticated -> 401")

    # 4. Key endpoint with auth but video doesn't exist in DB yet -> 404
    status, body = _get(f"/api/keys/{vid}", creator)
    assert status == 404, f"expected 404, got {status}"
    print("[ok] video not in DB yet -> 404")

    # 5. Check that key file was NOT generated yet (no /api/videos call)
    # The key is generated at POST /api/videos, not at upload-url.
    # (We can't fully test the transcode pipeline without uploading a binary,
    #  but we can test the key endpoint access control.)

    # 6. Verify that GET /api/keys/{nonexistent} with auth -> 404
    status, _ = _get("/api/keys/nonexistent_xyz", creator)
    assert status == 404
    print("[ok] nonexistent video -> 404")

    # 7. Check existing videos (from prior e2e tests) that were approved+ready
    #    but have NO key (legacy) -> should return 404 "not encrypted"
    _, videos = _get("/api/videos")
    vid_list = json.loads(videos)
    if vid_list["videos"]:
        existing_vid = vid_list["videos"][0]["id"]
        status, body = _get(f"/api/keys/{existing_vid}", creator)
        assert status == 404
        assert b"not encrypted" in body
        print(f"[ok] legacy video {existing_vid} -> 404 'not encrypted'")

    print("DRM e2e checks passed")


if __name__ == "__main__":
    main()

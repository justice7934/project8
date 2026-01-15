# app/video.py
import os
import httpx
import subprocess
import tempfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from security import verify_jwt
from minio_client import (
    upload_video,
    upload_thumbnail,
    get_video_stream,
    get_thumbnail_stream,
    list_user_videos,
)

router = APIRouter(tags=["video"])

KIE_API_URL = "https://api.kie.ai/api/v1/veo/generate"
KIE_API_KEY = os.getenv("KIE_API_KEY")

if not KIE_API_KEY:
    raise RuntimeError("KIE_API_KEY is not set")

# 메모리 상태 캐시 (선택적)
TASKS = {}

class VideoGenerateRequest(BaseModel):
    prompt: str


# 1️⃣ 영상 생성 요청
@router.post("/generate")
async def generate_video(body: VideoGenerateRequest, user=Depends(verify_jwt)):
    user_id = user["sub"]

    payload = {
        "prompt": body.prompt,
        "model": "veo3_fast",
        "aspect_ratio": "9:16",
        "callBackUrl": "http://auth.justic.store:8000/api/video/callback",
    }

    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(KIE_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    task_id = result.get("data", {}).get("taskId")
    if not task_id:
        raise HTTPException(status_code=502)

    TASKS[task_id] = {
        "status": "QUEUED",
        "user_id": user_id,
    }

    return {"task_id": task_id, "status": "QUEUED"}


# 2️⃣ 콜백
@router.post("/callback")
async def video_callback(payload: dict):
    task_id = payload.get("data", {}).get("taskId")
    urls = payload.get("data", {}).get("info", {}).get("resultUrls", [])

    task = TASKS.get(task_id)
    if not task or not urls:
        return {"code": 200}

    user_id = task["user_id"]

    tmp_video = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
            tmp_video = f.name

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.get(urls[0])
            r.raise_for_status()
            with open(tmp_video, "wb") as f:
                f.write(r.content)

        upload_video(user_id, task_id, tmp_video)
        task["status"] = "DONE"
    except Exception:
        task["status"] = "FAILED"
    finally:
        if tmp_video and os.path.exists(tmp_video):
            os.remove(tmp_video)

    return {"code": 200}


# 3️⃣ 영상 목록 (🔥 MinIO 기준)
@router.get("/list")
def list_videos(user=Depends(verify_jwt)):
    user_id = user["sub"]

    task_ids = list_user_videos(user_id)

    return {
        "videos": [
            {
                "task_id": tid,
                "status": TASKS.get(tid, {}).get("status", "DONE"),
            }
            for tid in task_ids
        ]
    }


# 4️⃣ 상태 조회
@router.get("/status/{task_id}")
def get_status(task_id: str, user=Depends(verify_jwt)):
    task = TASKS.get(task_id)
    return {
        "task_id": task_id,
        "status": task["status"] if task else "DONE"
    }


# 5️⃣ 영상 스트리밍 (🔥 MinIO 기준)
@router.get("/stream/{task_id}")
def stream_video(task_id: str, user=Depends(verify_jwt)):
    user_id = user["sub"]

    try:
        obj = get_video_stream(user_id, task_id)
    except Exception:
        raise HTTPException(status_code=404)

    def iterfile():
        for chunk in obj.stream(1024 * 1024):
            yield chunk
        obj.close()
        obj.release_conn()

    return StreamingResponse(iterfile(), media_type="video/mp4")


# 6️⃣ 썸네일
@router.get("/thumb/{task_id}.jpg")
def get_thumbnail(task_id: str, user=Depends(verify_jwt)):
    user_id = user["sub"]

    try:
        obj = get_thumbnail_stream(user_id, task_id)
    except Exception:
        # 없으면 생성
        tmp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        tmp_thumb = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg").name

        vobj = get_video_stream(user_id, task_id)
        with open(tmp_video, "wb") as f:
            for c in vobj.stream(1024 * 1024):
                f.write(c)

        subprocess.run(
            ["ffmpeg", "-y", "-ss", "00:00:01", "-i", tmp_video, "-frames:v", "1", tmp_thumb],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        upload_thumbnail(user_id, task_id, tmp_thumb)
        obj = get_thumbnail_stream(user_id, task_id)

        os.remove(tmp_video)
        os.remove(tmp_thumb)

    def iterthumb():
        for c in obj.stream(256 * 1024):
            yield c
        obj.close()
        obj.release_conn()

    return StreamingResponse(iterthumb(), media_type="image/jpeg")

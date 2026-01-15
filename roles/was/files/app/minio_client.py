# app/minio_client.py
import os
from minio import Minio
from minio.error import S3Error

MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")

minio_client = Minio(
    os.getenv("MINIO_ENDPOINT"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    secure=False
)

def ensure_bucket():
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)


def upload_video(user_id: str, task_id: str, file_path: str):
    minio_client.fput_object(
        MINIO_BUCKET,
        f"{user_id}/{task_id}.mp4",
        file_path,
        content_type="video/mp4"
    )


def upload_thumbnail(user_id: str, task_id: str, thumb_path: str):
    minio_client.fput_object(
        MINIO_BUCKET,
        f"{user_id}/{task_id}.jpg",
        thumb_path,
        content_type="image/jpeg"
    )


def get_video_stream(user_id: str, task_id: str):
    return minio_client.get_object(
        MINIO_BUCKET,
        f"{user_id}/{task_id}.mp4"
    )


def get_thumbnail_stream(user_id: str, task_id: str):
    return minio_client.get_object(
        MINIO_BUCKET,
        f"{user_id}/{task_id}.jpg"
    )


def list_user_videos(user_id: str):
    """
    MinIO 기준으로 유저 영상 목록 조회
    """
    objects = minio_client.list_objects(
        MINIO_BUCKET,
        prefix=f"{user_id}/",
        recursive=True,
    )

    videos = []
    for obj in objects:
        if obj.object_name.endswith(".mp4"):
            task_id = obj.object_name.split("/")[-1].replace(".mp4", "")
            videos.append(task_id)

    return sorted(videos, reverse=True)

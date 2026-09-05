import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime

CHANNEL = "vector"
KICK_API_URL = f"https://kick.com/api/v2/channels/{CHANNEL}/videos"
WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/mnt/workspace"))

GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
GITHUB_ENV = Path(os.environ["GITHUB_ENV"])

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "Accept": "application/json",
}

GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "vod-release-workflow",
}


def write_env(name, value):
    """Guarda una variable para los siguientes pasos del workflow."""
    with GITHUB_ENV.open("a", encoding="utf-8") as env_file:
        if "\n" in str(value):
            env_file.write(f"{name}<<EOF\n{value}\nEOF\n")
        else:
            env_file.write(f"{name}={value}\n")


def open_json(url, headers):
    """Hace una petición GET y devuelve el JSON de la respuesta."""
    request = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(request) as response:
        return json.load(response)


def write_json(path, data):
    """Guarda JSON con el mismo formato usado por el workflow original."""
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def release_exists(tag_name):
    """Comprueba si ya existe una release para este VOD."""
    encoded_tag = urllib.parse.quote(tag_name, safe="")

    url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/tags/"
        f"{encoded_tag}"
    )

    request = urllib.request.Request(url, headers=GITHUB_HEADERS)

    with urllib.request.urlopen(request):
        return True


def select_pending_video(videos):
    """Devuelve el VOD pendiente más antiguo con una fuente válida."""
    pending = sorted(
        (
            video
            for video in videos
            if video.get("is_live") is not True and video.get("source")
        ),
        key=lambda video: (
            video.get("created_at", ""),
            str(video.get("id", "")),
        ),
    )

    return next(
        (
            video
            for video in pending
            if not release_exists(f"vod-{video['id']}")
        ),
        None,
    )


def export_vod_environment(
    video_id,
    created_at,
    video_date,
    video_directory,
    file_name,
    tag_name,
    release_body,
):
    """Publica en GITHUB_ENV los datos que necesitan los siguientes pasos."""
    values = {
        "HAS_VOD": "true",
        "VOD_ID": video_id,
        "VOD_DATE": video_date,
        "VOD_CREATED_AT": created_at,
        "VOD_DIR": video_directory,
        "FILE_NAME": file_name,
        "RELEASE_TAG": tag_name,
        "RELEASE_NAME": f"{CHANNEL.capitalize()} | VOD | {video_date} | {video_id}",
        "RELEASE_BODY": release_body,
    }

    for name, value in values.items():
        write_env(name, value)


videos = open_json(KICK_API_URL, HTTP_HEADERS)

WORKSPACE.mkdir(parents=True, exist_ok=True)

write_json(
    WORKSPACE / "videos.json",
    videos,
)

selected_video = select_pending_video(videos)

if selected_video is None:
    write_env("HAS_VOD", "false")
    print("No hay VODs pendientes para publicar.")
    raise SystemExit(0)

video_id = selected_video["id"]
created_at = str(selected_video.get("created_at", "unknown"))

video_date = created_at.split("T")[0].split(" ")[0]

release_date = (
    datetime.fromisoformat(
        created_at.replace("Z", "+00:00")
    ).strftime("%d/%m/%Y")
    if created_at != "unknown"
    else "unknown"
)

title = (
    selected_video.get("session_title")
    or selected_video.get("title")
    or selected_video.get("name")
    or "Sin título"
)

source_url = selected_video["source"]

release_body = (
    f"{CHANNEL.capitalize()} | {release_date}\n\n"
    f"{title}\n\n"
    f"{created_at}\n\n"
    f"{source_url}"
)

tag_name = f"vod-{video_id}"
file_name = f"{CHANNEL}_{video_date}_{video_id}.ts"

video_directory = WORKSPACE / f"{video_date}_{video_id}"

video_directory.mkdir(
    parents=True,
    exist_ok=True,
)

write_json(
    video_directory / "video.json",
    selected_video,
)

output_path = video_directory / file_name

subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-i",
        selected_video["source"],
        "-c",
        "copy",
        str(output_path),
    ],
    check=True,
)

export_vod_environment(
    video_id,
    created_at,
    video_date,
    video_directory,
    file_name,
    tag_name,
    release_body,
)

print(f"VOD seleccionado: {video_id} ({created_at})")

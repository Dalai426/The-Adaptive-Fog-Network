from fastapi import FastAPI, UploadFile, File, Form, Response, Request
import cv2
import numpy as np
import time
import psutil
import math
import requests
import hashlib
import os
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi.responses import JSONResponse
from slowapi import Limiter
from collections import defaultdict, deque

CLOUD_URL = os.environ.get("CLOUD")
EDGE_ID = os.environ.get("EDGE_ID")
offload_treshold = 512 * 1024  # 512 KB


app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
ip_uploads = defaultdict(deque)
banned_ips = {}


async def rate_limit_handler(request: Request, exc: Exception) -> Response:
    client_ip = get_remote_address(request)
    print("Too many requests from IP of %s", client_ip, flush=True)
    return JSONResponse(
        status_code=429, content={"error": "Too many requests", "client_ip": client_ip}
    )


app.add_exception_handler(RateLimitExceeded, handler=rate_limit_handler)

cpu_limit = None
memory_limit = None


def process_image(image):
    return cv2.GaussianBlur(image, (7, 7), 1.5)


def process_remote(image, file: UploadFile):
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("PNG encoding failed")
    response = requests.post(
        f"{CLOUD_URL}/process-part",
        files={"file": (file.filename, encoded.tobytes(), "image/png")},
        timeout=60,
    )
    response.raise_for_status()
    result = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    if result is None:
        raise RuntimeError("Invalid cloud response")
    return result


def check_upload_limit(ip, size):
    now = time.monotonic()
    uploads = ip_uploads[ip]
    # 10MB limit every 15 seconds
    # Remove uploads older than 15 seconds
    while uploads and now - uploads[0][0] >= 15:
        uploads.popleft()
    total_uploaded = sum(upload_size for timestamp, upload_size in uploads)
    if total_uploaded + size > 10 * 1024 * 1024:  # 10MB
        return False
    uploads.append((now, size))
    return True


@app.middleware("http")
async def upload_size_limit(request: Request, call_next):

    if request.url.path == "/process" and request.method == "POST":
        client_ip = get_remote_address(request)
        if client_ip in banned_ips:
            if time.monotonic() < banned_ips[client_ip]:
                return JSONResponse(
                    status_code=403,
                    content={"error": "IP temporarily banned"},
                )
            del banned_ips[client_ip]
        file_size = request.headers.get("X-File-Size")
        if file_size is None or not file_size.isdigit():
            banned_ips[client_ip] = time.monotonic() + 60
            print(
                f"INVALID FILE SIZE HEADER | IP: {client_ip}",
                flush=True,
            )
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid file size header"},
            )
        file_size = int(file_size)
        if file_size > 10 * 1024 * 1024:
            return JSONResponse(
                status_code=413,
                content={"error": "File too large"},
            )

        if not check_upload_limit(client_ip, file_size):
            print(
                f"UPLOAD QUOTA EXCEEDED | IP: {client_ip}",
                flush=True,
            )
            return JSONResponse(
                status_code=429,
                content={"error": "Upload quota exceeded"},
            )

    return await call_next(request)


def get_container_cpu_usage():
    with open("/sys/fs/cgroup/cpu.stat") as f:
        stats = dict(line.split() for line in f)

    return int(stats["usage_usec"])


@app.post("/process")
@limiter.limit("2/second")
async def process(
    request: Request,
    file: UploadFile = File(...),
    image_id: str = Form(...),
    camera_id: str = Form(...),
):
    client_ip = get_remote_address(request)
    header_file_size = int(request.headers["X-File-Size"])
    start = time.perf_counter()
    cloud_elapsed = 0

    data = await file.read()
    actual_size = len(data)

    if header_file_size != actual_size:
        banned_ips[client_ip] = time.monotonic() + 60
        print(
            f"FILE SIZE MISMATCH | IP: {client_ip} | "
            f"Declared: {header_file_size} | "
            f"Actual: {actual_size}",
            flush=True,
        )
        return JSONResponse(
            status_code=403,
            content={"error": "File size mismatch. IP banned for 60 seconds"},
        )

    start = time.perf_counter()
    cloud_elapsed = 0
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    if image is None or image.size == 0:
        return {"error": "Invalid image"}

    height, width = image.shape[:2]
    if len(data) <= offload_treshold:
        result = process_image(image)
        decision = "LOCAL"
        offload_ratio = 0
    else:
        pid = psutil.Process()
        cpu_usage = pid.cpu_percent(interval=0.1)
        memory_usage = psutil.virtual_memory().percent

        cpu_pressure = cpu_usage / 100
        memory_pressure = memory_usage / 100

        if cpu_pressure == 0 and memory_pressure == 0:
            offload_ratio = 0
        else:
            offload_ratio = math.sqrt(0.6 * cpu_pressure**2 + 0.4 * memory_pressure**2)

        if offload_ratio == 0:
            result = process_image(image)
            decision = "LOCAL"
        else:
            split_y = int(height * (1 - offload_ratio))
            split_y = max(1, min(height, split_y))

            local_start = 0
            local_end = split_y
            kernel_radius = 3

            local_chunk = image[local_start : (local_end + kernel_radius), :]
            local_processed = process_image(local_chunk)
            local_result = local_processed[:local_end, :]

            # Cloud processing
            remote_start = max(0, split_y - kernel_radius)
            remote_end = height

            remote_chunk = image[remote_start:remote_end, :]
            if remote_chunk.size == 0:
                print("Remote chunk is empty")
            else:
                print("Remote chunk is not empty")

            cloud_start = time.perf_counter()
            remote_processed = process_remote(remote_chunk, file)
            cloud_elapsed = time.perf_counter() - cloud_start
            # Remove overlapping rows
            remote_result = remote_processed[split_y - remote_start :, :]
            # Reassemble both sections
            result = np.vstack([local_result, remote_result])

            decision = "HYBRID"

    # Verify the hybrid result
    reference = process_image(image)
    result_hash = hashlib.sha256(result.tobytes()).hexdigest()
    reference_hash = hashlib.sha256(reference.tobytes()).hexdigest()

    matches = result_hash == reference_hash

    elapsed = time.perf_counter() - start

    print(
        f"Image: {image_id} | "
        f"Camera: {camera_id} | "
        f"Edge: {EDGE_ID} | "
        f"Size: {len(data)} bytes | "
        f"Decision: {decision} | "
        f"Offloaded: {offload_ratio * 100:.0f}% | "
        f"Hash match: {matches} | "
        f"Time: {elapsed:.4f}s | "
        f"Cloud Processing Time: {cloud_elapsed:.4f}s"
    )

    if not matches:
        return {"error": "Distributed result differs from reference"}

    success, encoded = cv2.imencode(".png", result)
    if not success:
        raise RuntimeError("PNG encoding failed")

    return Response(
        content=result.tobytes(),
        media_type="image/png",
        headers={
            "X-Image-ID": image_id,
            "X-Decision": decision,
            "X-Edge-ID": str(EDGE_ID),
            "X-Offload-Ratio": str(offload_ratio),
            "X-Processing-Time": str(elapsed),
            "X-Hash-Match": str(matches),
            "X-Output-SHA256": result_hash,
        },
    )

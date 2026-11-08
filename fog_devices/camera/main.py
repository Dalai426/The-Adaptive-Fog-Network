import argparse
import cv2
import numpy as np
import time
import requests
import uuid
import os
from concurrent.futures import ThreadPoolExecutor

CAMERA_ID = os.environ.get("CAMERA_ID")
FOG_URL = os.environ.get("FOG")
ATTACK_MODE = os.getenv("ATTACK_MODE", "false").lower() == "true"


def send_image(image):
    success, encoded = cv2.imencode(".jpg", image)
    if not success:
        raise RuntimeError("Image encoding failed")

    image_id = str(uuid.uuid4())

    try:
        image_bytes = encoded.tobytes()
        start = time.perf_counter()
        response = requests.post(
            f"{FOG_URL}/process",
            files={
                "file": (
                    f"camera_{CAMERA_ID}_${image_id}.jpg",
                    # 5MB
                    image_bytes,
                    "image/jpeg",
                )
            },
            headers={
                "X-File-Size": str(len(image_bytes)),
            },
            data={"image_id": image_id, "camera_id": CAMERA_ID},
        )
        elapsed = time.perf_counter() - start
        if response.status_code == 200:
            print(
                f"Camera: {CAMERA_ID} | "
                f"Status: Success | "
                f"Total Request Time: {elapsed:.4f}s | "
                f"Fog Processing Time: {response.headers.get('X-Processing-Time')}s",
                flush=True,
            )
        else:
            print("Error:", response.text, flush=True)
    except Exception as exc:
        print(exc, flush=True)


def generate_image():
    height, width = 1080, 1920
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:] = (65, 110, 75)

    # Add random terrain texture
    noise = np.random.normal(0, 18, (height, width, 1))

    image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    cv2.line(image, (100, 900), (1500, 100), (110, 110, 110), 45)
    for _ in range(30):
        x = np.random.randint(0, width - 80)
        y = np.random.randint(0, height - 80)

        cv2.rectangle(image, (x, y), (x + 60, y + 60), (130, 130, 120), -1)

    for _ in range(15):
        x = np.random.randint(0, width)
        y = np.random.randint(0, height)

        cv2.circle(image, (x, y), 12, (0, 0, 255), -1)

    return image


def normal_mode():
    print("NORMAL CAMERA MODE", flush=True)
    while True:
        image = generate_image()
        send_image(image)
        time.sleep(5)


def attack_mode():
    print("ATTACK CAMERA MODE", flush=True)

    # Fixed number of concurrent requests; no unbounded queue.
    with ThreadPoolExecutor(max_workers=50) as executor:
        pending = set()
        while True:
            pending = {f for f in pending if not f.done()}
            if len(pending) < 50:
                image = generate_image()
                pending.add(executor.submit(send_image, image))


if __name__ == "__main__":
    print(f"Starting camera {CAMERA_ID}", flush=True)
    print(f"Fog node: {FOG_URL}", flush=True)
    try:
        if ATTACK_MODE:
            attack_mode()
        else:
            normal_mode()
    except KeyboardInterrupt:
        print(f"\nCamera {CAMERA_ID} stopped.", flush=True)

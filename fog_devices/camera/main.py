import argparse
import cv2
import numpy as np
import time
import requests
import uuid
import os

CAMERA_ID = os.environ.get("CAMERA_ID")
FOG_URL = os.environ.get("FOG")


def send_image(image):
    success, encoded = cv2.imencode(".jpg", image)
    if not success:
        raise RuntimeError("Image encoding failed")

    start = time.perf_counter()
    image_id = str(uuid.uuid4())

    try:
        response = requests.post(
            f"{FOG_URL}/process",
            files={
                "file": (
                    f"camera_{CAMERA_ID}_${image_id}.jpg",
                    encoded.tobytes(),
                    "image/jpeg",
                )
            },
            data={"image_id": image_id, "camera_id": CAMERA_ID},
        )
        elapsed = time.perf_counter() - start
        if response.status_code == 200:
            print(f"Camera {CAMERA_ID}: image sent successfully")
            print(f"Total request time: {elapsed:.4f}s")
            print(
                "Fog processing time:",
                response.headers.get("X-Processing-Time"),
                "seconds",
            )
        else:
            print("Error:", response.text)
    except Exception as exc:
        print(exc)


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


if __name__ == "__main__":
    print(f"Starting camera {CAMERA_ID}")
    print(f"Fog node: {FOG_URL}")
    try:
        while True:
            image = generate_image()
            send_image(image)
            time.sleep(2.0)

    except KeyboardInterrupt:
        print(f"\nCamera {CAMERA_ID} stopped.")

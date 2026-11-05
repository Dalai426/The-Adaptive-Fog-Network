from fastapi import FastAPI, UploadFile, File
from fastapi.responses import Response
import cv2
import numpy as np
import time

app = FastAPI()
print("Cloud device is running...")


@app.post("/process-part")
async def process_part(file: UploadFile = File(...)):

    start = time.perf_counter()
    data = await file.read()
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return {"error": "Invalid image"}

    result = cv2.GaussianBlur(image, (7, 7), 1.5)

    success, encoded = cv2.imencode(".png", result)

    elapsed = time.perf_counter() - start

    if not success:
        return {"error": "Encoding failed"}
    print(f"The cloud spends {elapsed:.4f}s processing the {file.filename} file")
    return Response(content=encoded.tobytes(), media_type="image/png")

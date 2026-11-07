### Command for Starting a Camera
FOG=http://127.0.0.1:8000  CAMERA_ID=camera1 python camera/main.py
### Command for Starting a Edge Device
CLOUD=http://127.0.0.1:8001 EDGE_ID=edge1 uvicorn fog.main:app --host 0.0.0.0 --port 8000
### Command for Starting a Cloud
uvicorn cloud.main:app --host 0.0.0.0 --port 8001
### Command for Starting Logger
docker compose -f docker-compose-logging.yml up -d
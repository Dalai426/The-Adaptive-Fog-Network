FROM python:3.12-slim

WORKDIR /app


COPY requirement.txt ./
RUN pip install -r requirement.txt

RUN apt-get update && \
    apt-get install -y iproute2 iputils-ping && \
    rm -rf /var/lib/apt/lists/*

COPY ./fog ./

CMD ["sh", "-c", "tc qdisc replace dev eth0 root netem delay 200ms && exec uvicorn main:app --host 0.0.0.0 --port 8000"]

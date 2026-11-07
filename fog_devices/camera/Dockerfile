FROM python:3.12-slim

WORKDIR /app


COPY requirement.txt ./
RUN pip install -r requirement.txt

COPY ./camera ./

CMD ["python", "main.py"]
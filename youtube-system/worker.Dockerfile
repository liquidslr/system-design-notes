FROM python:3.11-slim

# ffmpeg is required for transcoding (design doc: Task Workers run ffmpeg)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_RETRIES=10 \
    PIP_TIMEOUT=120

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY worker ./worker

EXPOSE 8001
CMD ["python", "-m", "worker.main"]

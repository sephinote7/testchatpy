# Python + OpenJDK (konlpy/Okt용). Render 등에서 JVM 필요 시 이 Dockerfile 사용
FROM python:3.12-slim-bookworm

# OpenJDK 17 JRE (konlpy/Okt 의존성)
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render는 런타임에 PORT 환경변수 지정
EXPOSE 10000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]

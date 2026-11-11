FROM python:3.11-slim

WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# Ollama는 컨테이너 밖(호스트)에서 실행한다고 가정
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434
EXPOSE 8000

# job 저장소가 인메모리이므로 워커는 반드시 1개
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

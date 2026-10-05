# Pipeline image for Cloud Batch / Cloud Run jobs. Entry point: python -m airo <command>
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY glossaries ./glossaries
RUN pip install --no-cache-dir ".[gemini,gcs]"
ENV AIRO_GLOSSARIES=/app/glossaries

ENTRYPOINT ["python", "-m", "airo"]

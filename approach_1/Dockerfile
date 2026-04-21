# Dockerfile

FROM python:3.11-slim

# System deps (pdfplumber sometimes wants these)
RUN apt-get update && apt-get install -y \
    gcc \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run will set PORT; default 8080 for local
ENV PORT=8080

# Gunicorn entrypoint
CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app"]

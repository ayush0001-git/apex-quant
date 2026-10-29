# Apex Quant-Terminal v1.2.0 Docker Image
FROM python:3.12-slim

LABEL maintainer="Apex Quant Labs"
LABEL version="1.2.0"
LABEL description="Institutional-Grade Quant Trading Terminal for NSE/BSE Equities"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e .

# Copy application source code
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/monitoring/health || exit 1

# Run uvicorn server
CMD ["python", "-m", "uvicorn", "src.apex.interface.api:app", "--host", "0.0.0.0", "--port", "8000"]

# Use official Python image with slim-buster base
FROM python:3.10-slim-buster as builder

# Install build dependencies (for wheels like pydantic, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install wheels
RUN pip install --upgrade pip setuptools wheel

# Install dependencies first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Runtime Stage ---
FROM python:3.10-slim-buster

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Set working directory
WORKDIR /app

# Copy only necessary files (exclude .git, __pycache__ etc.)
COPY --chown=appuser:appuser main.py .
COPY --chown=appuser:appuser app/ ./app/  # If you have an "app" module

# Expose port (match with Fly.io internal port)
EXPOSE 8080  # Fly.io uses 8080 by default

# Health check for Fly.io
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:8080/health || exit 1

# Run Uvicorn (adjust module name as needed)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]

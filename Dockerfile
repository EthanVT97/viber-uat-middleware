# =============================
# Stage 1 – Builder
# =============================
FROM python:3.10-slim-buster as builder

# Install system build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    curl \
    git && \
    rm -rf /var/lib/apt/lists/*

# Set up Rust environment for maturin (used by some FastAPI extensions)
ENV CARGO_HOME=/cargo
ENV RUSTUP_HOME=/rustup
ENV PATH="${CARGO_HOME}/bin:${PATH}"

RUN curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal

# Create Python virtualenv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --no-build-isolation -r requirements.txt

# =============================
# Stage 2 – Runtime
# =============================
FROM python:3.10-slim-buster

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# System environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/home/appuser

# Create a non-root user and secure workspace
RUN useradd -m appuser && mkdir -p /app && chown -R appuser:appuser /app
WORKDIR /app
USER appuser

# Copy project files (adapt if needed)
COPY --chown=appuser:appuser main.py .
COPY --chown=appuser:appuser config.py .
COPY --chown=appuser:appuser log_storage.py .
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser templates/ ./templates/

# Expose HTTP port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD curl -f http://localhost:8080/health || exit 1

# Start FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]

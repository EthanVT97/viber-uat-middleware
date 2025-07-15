--- START OF FILE viber-uat-middleware-main/Dockerfile ---

# Use official Python image with slim-buster base
FROM python:3.10-slim-buster as builder

# Install build dependencies (for wheels like pydantic, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    # Clean up apt caches to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Set HOME to a writable directory like /tmp during the build stage.
# This ensures that tools like Cargo/Rustup (used by pydantic for its Rust extensions)
# write their caches and registries to a writable location, preventing "Read-only file system" errors.
ENV HOME=/tmp

# Set CARGO_HOME and RUSTUP_HOME to subdirectories within HOME for proper Rust toolchain management.
ENV CARGO_HOME="$HOME/.cargo"
ENV RUSTUP_HOME="$HOME/.rustup"

# Explicitly create these directories to ensure they exist and are writable
RUN mkdir -p "$CARGO_HOME" "$RUSTUP_HOME"

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

# Reset HOME to something more conventional for the app user, or leave it as default.
# If HOME needs to be writable for runtime operations, ensure /appuser's home is accessible.
# Default for useradd -m is /home/appuser.
ENV HOME=/home/appuser # Reset HOME for the runtime stage, as build-time settings are no longer needed.

# Set non-root user for security
# Ensure /appuser's home directory is created and owned correctly
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Set working directory
WORKDIR /app

# Copy only necessary files (exclude .git, __pycache__ etc.)
COPY --chown=appuser:appuser main.py .
COPY --chown=appuser:appuser config.py .
COPY --chown=appuser:appuser log_storage.py .
COPY --chown=appuser:appuser app/ ./app/  # If you have an "app" module, make sure it exists
COPY --chown=appuser:appuser templates/ ./templates/

# Expose port (match with Fly.io internal port)
EXPOSE 8080  # Fly.io uses 8080 by default

# Health check for Fly.io
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:8080/health || exit 1

# Run Uvicorn (adjust module name as needed)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
--- END OF FILE viber-uat-middleware-main/Dockerfile ---

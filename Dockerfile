--- START OF FILE viber-uat-middleware-main/Dockerfile ---

# Use official Python image with slim-buster base
FROM python:3.10-slim-buster as builder

# Install common build dependencies, including curl for Rustup
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    curl \ # Add curl to download rustup installer
    && rm -rf /var/lib/apt/lists/*

# Set HOME to a writable directory like /tmp during the build stage.
# This ensures that tools like Cargo/Rustup (used by pydantic's Rust extensions)
# write their caches and registries to a writable location, preventing "Read-only file system" errors.
ENV HOME=/tmp

# Explicitly define Cargo/Rustup home directories relative to HOME.
# This is crucial for forcing Rust toolchain to use /tmp.
ENV CARGO_HOME="$HOME/.cargo"
ENV RUSTUP_HOME="$HOME/.rustup"

# Install Rust toolchain (rustup and cargo) into the writable /tmp directory.
# -y: yes to all prompts
# --no-modify-path: we will manage PATH ourselves
# --profile minimal: install only essential components to keep image smaller
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal \
    # Ensure generated directories have proper permissions if needed, though rustup usually handles this.
    && chmod -R a+rwx "$CARGO_HOME" "$RUSTUP_HOME"

# Add Cargo's bin directory to PATH for the current builder stage.
# This makes `cargo` and `maturin` available for subsequent pip installs.
ENV PATH="$CARGO_HOME/bin:$PATH"

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install wheels
RUN pip install --upgrade pip setuptools wheel

# Install dependencies first for caching
COPY requirements.txt .
# Run pip install with a temporary build directory for greater robustness
RUN pip install --no-cache-dir --build-option="--build-dir=/tmp/pip-build" -r requirements.txt

# --- Runtime Stage ---
FROM python:3.10-slim-buster

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Reset HOME to the app user's home directory for the runtime stage.
# This ensures a clean and conventional environment for the running application.
ENV HOME=/home/appuser

# Set non-root user for security
# Ensure /home/appuser directory is created and owned correctly for the appuser.
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

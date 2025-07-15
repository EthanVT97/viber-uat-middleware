# Use official Python image with slim-buster base for the builder stage
FROM python:3.10-slim-buster as builder

# Install common build dependencies
# curl is needed for installing rustup.
# build-essential and libffi-dev are typically required for many Python packages
# that include C/C++ or Rust extensions (like pydantic_core).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    curl && \
    rm -rf /var/lib/apt/lists/*

# --- Configure Rust Toolchain for Writable Access ---
# This section is CRITICAL for preventing "Read-only file system" errors
# when pydantic-core (or other Rust-based packages) is built.

# Set HOME to a writable directory like /tmp during the build stage.
# This ensures that tools like Cargo/Rustup write their caches and registries
# to a location where they have permissions.
ENV HOME=/tmp

# Explicitly define Cargo and Rustup home directories relative to HOME.
# This forces the Rust toolchain to use /tmp for its files.
ENV CARGO_HOME="$HOME/.cargo"
ENV RUSTUP_HOME="$HOME/.rustup"

# Add Cargo's bin directory to PATH for the current builder stage.
# This makes `cargo` and `maturin` (which relies on cargo) available for
# subsequent pip installs.
ENV PATH="$CARGO_HOME/bin:$PATH"

# Install Rust toolchain (rustup and cargo) into the writable /tmp directory.
# -y: yes to all prompts
# --no-modify-path: we will manage PATH ourselves
# --profile minimal: install only essential components to keep image smaller
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal && \
    # Ensure generated directories have proper permissions (rustup usually handles this, but being explicit doesn't hurt)
    chmod -R a+rwx "$CARGO_HOME" "$RUSTUP_HOME"

# --- Python Virtual Environment Setup ---

# Create Python virtual environment
RUN python -m venv /opt/venv
# Add the virtual environment's bin directory to PATH
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install `maturin` and other essential build tools.
# Explicitly installing `maturin` ensures it's available in the main environment
# where our CARGO_HOME setup is active, preventing issues with pip's isolated builds.
RUN pip install --upgrade pip setuptools wheel maturin

# Copy requirements.txt and install Python dependencies.
# Copying requirements.txt separately allows Docker to cache this layer
# if requirements don't change, speeding up subsequent builds.
COPY requirements.txt .
# --no-cache-dir: Disables pip's internal package cache, good for smaller images.
# --no-build-isolation: Prevents pip from installing build dependencies (like maturin)
#                       into a temporary isolated environment. This is CRITICAL here
#                       because it forces the build to use our controlled CARGO_HOME.
RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

# --- Runtime Stage ---
# Use the same lean Python base image for consistency and smaller final image size.
FROM python:3.10-slim-buster

# Copy the pre-built virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
# Set the PATH to include the virtual environment's binaries
ENV PATH="/opt/venv/bin:$PATH"

# Reset HOME to a clean, conventional directory for the runtime stage.
# This ensures a clean environment for the running application and avoids
# any potential conflicts with the /tmp used during the build.
ENV HOME=/home/appuser

# Create a dedicated non-root user and application directory for security.
# useradd -m creates the home directory (/home/appuser).
# mkdir -p /app creates the application directory if it doesn't exist.
# chown ensures the app directory and its contents are owned by the non-root user.
RUN useradd -m appuser && \
    mkdir -p /app && \
    chown -R appuser:appuser /app

# Set the working directory for the application
WORKDIR /app

# Switch to the non-root user. All subsequent commands will run as 'appuser'.
USER appuser

# Copy application files into the /app directory.
# --chown ensures files are owned by the appuser when copied.
# Make sure these paths match your actual project structure.
COPY --chown=appuser:appuser main.py .
COPY --chown=appuser:appuser config.py .
COPY --chown=appuser:appuser log_storage.py .
COPY --chown=appuser:appuser app/ ./app/           # If 'app' is a module directory
COPY --chown=appuser:appuser templates/ ./templates/ # If 'templates' is a directory

# Expose the port your application listens on (e.g., for Fly.io, Render, etc.)
EXPOSE 8080

# Define a health check for container orchestration platforms.
# --start-period gives the app time to initialize before health checks begin.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD curl -f http://localhost:8080/health || exit 1

# Command to run the application using Uvicorn.
# Adjust "main:app" if your FastAPI/Starlette app is defined elsewhere.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]

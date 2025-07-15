FROM python:3.10-slim-buster as builder

# Install common build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    curl && \
    rm -rf /var/lib/apt/lists/*

# --- Configure Rust Toolchain for Writable Access ---
ENV HOME=/tmp
ENV CARGO_HOME="$HOME/.cargo"
ENV RUSTUP_HOME="$HOME/.rustup"
ENV PATH="$CARGO_HOME/bin:$PATH"

# Install Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal && \
    chmod -R a+rwx "$CARGO_HOME" "$RUSTUP_HOME"

# --- DEBUGGING LINES START ---
# These lines will print the environment variables right before pip install
RUN echo "DEBUG (Before venv, Before pip):"
RUN echo "DEBUG: HOME=$HOME"
RUN echo "DEBUG: CARGO_HOME=$CARGO_HOME"
RUN echo "DEBUG: RUSTUP_HOME=$RUSTUP_HOME"
RUN echo "DEBUG: PATH=$PATH"
RUN which cargo || echo "cargo not found yet in PATH"
RUN cargo --version || echo "cargo --version failed"
# --- DEBUGGING LINES END ---

# Create Python virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install `maturin`
RUN pip install --upgrade pip setuptools wheel maturin

# --- DEBUGGING LINES START ---
# These lines will print the environment variables right before pip install
RUN echo "DEBUG (After venv, Before pip):"
RUN echo "DEBUG: HOME=$HOME"
RUN echo "DEBUG: CARGO_HOME=$CARGO_HOME"
RUN echo "DEBUG: RUSTUP_HOME=$RUSTUP_HOME"
RUN echo "DEBUG: PATH=$PATH"
RUN which cargo || echo "cargo not found in venv PATH"
RUN cargo --version || echo "cargo --version failed in venv PATH"
RUN which python
RUN python --version
RUN which pip
RUN pip --version
RUN which maturin
# --- DEBUGGING LINES END ---

# Copy requirements.txt and install Python dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

# --- Runtime Stage (rest of your Dockerfile remains the same) ---
FROM python:3.10-slim-buster

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

ENV HOME=/home/appuser

RUN useradd -m appuser && \
    mkdir -p /app && \
    chown -R appuser:appuser /app

WORKDIR /app
USER appuser

COPY --chown=appuser:appuser main.py .
COPY --chown=appuser:appuser config.py .
COPY --chown=appuser:appuser log_storage.py .
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser templates/ ./templates/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]

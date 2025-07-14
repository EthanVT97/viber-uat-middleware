FROM python:3.10-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies first.
# This leverages Docker's layer caching: if requirements.txt doesn't change,
# this step won't re-run, speeding up subsequent builds.
COPY requirements.txt .

# Install build dependencies that Pydantic (and others) might need.
# These typically include build-essential for C/C++ compilers, and possibly libffi-dev, etc.
# Also, upgrade pip, setuptools, and wheel for best wheel compatibility.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port your FastAPI application will listen on.
# This should match the port specified in your uvicorn command.
EXPOSE 10000

# Command to run your application.
# Use 0.0.0.0 for the host to make it accessible outside the container.
# Use the same port as EXPOSE.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]

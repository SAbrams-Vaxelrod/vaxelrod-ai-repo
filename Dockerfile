# Use the official AWS Lambda Python 3.11 base image
FROM public.ecr.aws/lambda/python:3.11

# Add a build argument to force a clean installation when building
ARG CACHE_BUST=0

# Set environment variables for clean execution
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy requirements file first to leverage Docker layer caching
COPY requirements.txt ./

# **EXPERT FIX**: Aggressively purge any pre-existing or cached versions of Google's SDK
# before installing the correct version from requirements.txt.
RUN python -m pip install --upgrade pip && \
    python -m pip uninstall -y google-generativeai || true && \
    rm -rf /root/.cache/pip /var/lang/lib/python*/site-packages/google* /opt/python/lib/python*/site-packages/google* || true && \
    python -m pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY quoter.py ./

# Set the command to run when the container starts
CMD ["quoter.lambda_handler"]

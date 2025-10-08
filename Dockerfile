# Use the official AWS Lambda Python 3.11 base image
FROM public.ecr.aws/lambda/python:3.11

ARG CACHE_BUST=0

# Set environment variables for clean execution
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy requirements file first to leverage Docker layer caching
COPY requirements.txt ./

# Install Python dependencies cleanly
RUN python -m pip install --upgrade pip && \
    python -m pip uninstall -y google-generativeai || true && \
    python -m pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY quoter.py ./

# Set the command to run when the container starts
CMD ["quoter.lambda_handler"]
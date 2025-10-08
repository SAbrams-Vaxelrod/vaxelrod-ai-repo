# Use the official AWS Lambda Python 3.11 base image
FROM public.ecr.aws/lambda/python:3.11

ARG CACHE_BUST=0

# Set environment variables for clean execution
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy requirements file first
COPY scraper-requirements.txt ./

# Install Python dependencies
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r scraper-requirements.txt

# Copy the application code into the container
COPY scraper.py ./

# Set the command to run when the container starts
CMD ["scraper.lambda_handler"]
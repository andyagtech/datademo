FROM python:3.14-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code (data is mounted at runtime, not baked into image)
COPY src/ src/
COPY tests/ tests/

# Default command: run the full pipeline
CMD ["python", "-m", "src.main"]

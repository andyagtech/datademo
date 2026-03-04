FROM python:3.13-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY src/ src/
COPY tests/ tests/
COPY scripts/ scripts/
COPY docs/ docs/
COPY specs/ specs/

# Create output directories and symlinks expected by the web UI
RUN mkdir -p reports/exports \
    && ln -sfn ../reports/exports docs/exports \
    && ln -sfn ../reports docs/reports

# Expose port for the documentation web server
EXPOSE 8888

# Default: run full pipeline, render docs, then serve the web UI
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]

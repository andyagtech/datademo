FROM python:3.14-slim

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

# Root-level files needed by render_md_docs.py and pytest
COPY REVIEWER_README.md FEEDBACK.md pyproject.toml ./

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

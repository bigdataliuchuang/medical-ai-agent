# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM continuumio/miniconda3:24.11.1-0 AS builder

WORKDIR /build

COPY environment.yml ./
RUN conda env create -f environment.yml && conda clean -afy

COPY pyproject.toml ./
COPY src/ src/
RUN conda run --no-capture-output -n ai-data-agent pip install --no-cache-dir .

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM continuumio/miniconda3:24.11.1-0

LABEL maintainer="medical-data-governance"
LABEL description="AI Data Agent - Medical Data Governance Text-to-SQL"

WORKDIR /app

# Copy conda env from builder
COPY --from=builder /opt/conda/envs/ai-data-agent /opt/conda/envs/ai-data-agent

# Copy application code and metadata
COPY pyproject.toml ./
COPY src/ src/
COPY metadata/ metadata/
COPY config/ config/
COPY evaluation/ evaluation/
COPY scripts/ scripts/

# Install app in runtime env
SHELL ["conda", "run", "--no-capture-output", "-n", "ai-data-agent", "/bin/bash", "-c"]
RUN pip install --no-cache-dir --no-deps .

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENV AI_DATA_AGENT_CONFIG=config/application.local.yaml
ENV AI_DATA_AGENT_METADATA_ROOT=metadata

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["conda", "run", "--no-capture-output", "-n", "ai-data-agent", \
     "python", "-m", "uvicorn", "ai_data_agent.api.app:app", \
     "--host", "0.0.0.0", "--port", "8000"]

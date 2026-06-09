# CausalGame simulation backend
FROM python:3.11-slim

WORKDIR /app

# Install backend dependencies
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the simulation engine and scenario configs
COPY api/ ./api/
COPY experiments/ ./experiments/
COPY config/ ./config/

# Interaction logs
RUN mkdir -p /app/agent_records

# Default scenario
ENV CAUSALGAME_EXPERIMENT=antenna_trap

EXPOSE 8000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir '.[proxy]'
RUN useradd --uid 10001 --create-home litellm
COPY --chmod=644 config.example.yaml /app/config.yaml
COPY --chmod=644 proxy_handler.py /app/proxy_handler.py
USER litellm
EXPOSE 4000
CMD ["litellm", "--config", "/app/config.yaml", "--host", "0.0.0.0", "--port", "4000"]

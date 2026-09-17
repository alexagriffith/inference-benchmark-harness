FROM python:3.12-slim
WORKDIR /opt/harness
COPY pyproject.toml README.md LICENSE ./
COPY bench ./bench
RUN python -m pip install --no-cache-dir '.[runtime]'
ENV PYTHONDONTWRITEBYTECODE=1
ENV HF_HOME=/tmp/huggingface
USER 10001:10001
ENTRYPOINT ["python", "-m", "bench"]

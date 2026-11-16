FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY cloud.py .
COPY study.py study_models.py material_parser.py ./
COPY storage.py personal_summary.py ./
COPY qingjuan.py qingjuan_prompts.py ./
COPY billing.py .
COPY admin_release.py .
COPY release_manager.py .
COPY update-public-key.pem .
COPY learning-profile.schema.json .
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ECHO_DB=/data/accounts.sqlite
USER 65532:65532
EXPOSE 9090
HEALTHCHECK --interval=30s --timeout=4s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9090/healthz',timeout=3)"
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","9090","--workers","1","--limit-concurrency","20","--no-access-log","--no-proxy-headers"]

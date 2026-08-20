FROM codestra/identity-certification:20260816
COPY app.py /app/standby_auth.py
USER 65532:65532
CMD ["uvicorn", "standby_auth:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header", "--no-access-log"]

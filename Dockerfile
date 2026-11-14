# Pilot container: coordinator only. CPU workers run separately on consenting hosts.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system arkworld \
    && useradd --system --gid arkworld --home /app arkworld \
    && mkdir -p /data \
    && chown arkworld:arkworld /data
COPY . ./
USER arkworld
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM python:3.11-slim

WORKDIR /app

ARG PPT_MASTER_REPO_URL=https://github.com/hugohe3/ppt-master.git
ARG PPT_MASTER_REPO_REF=main

RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources

RUN apt-get -o Acquire::ForceIPv4=true -o Acquire::http::Timeout=20 -o Acquire::Retries=5 update && \
    apt-get install -y --no-install-recommends \
      git \
      pandoc \
      nodejs \
      npm \
      gcc \
      g++ \
      make \
      pkg-config \
      libcairo2 \
      libcairo2-dev \
      libpango-1.0-0 \
      libpangocairo-1.0-0 \
      libgdk-pixbuf-2.0-0 \
      shared-mime-info \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch ${PPT_MASTER_REPO_REF} ${PPT_MASTER_REPO_URL} /opt/ppt-master

COPY requirements.txt /tmp/service-requirements.txt
COPY . /app
RUN pip install --no-cache-dir --default-timeout=180 --retries 8 -i https://pypi.tuna.tsinghua.edu.cn/simple -r /tmp/service-requirements.txt && \
    pip install --no-cache-dir --default-timeout=180 --retries 8 -i https://pypi.tuna.tsinghua.edu.cn/simple -r /opt/ppt-master/requirements.txt

ENV PYTHONPATH=/app

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8099"]

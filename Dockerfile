FROM python:3.11-slim-trixie
EXPOSE 8080

ENV TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY fonts/ /usr/shared/fonts/chinese/

# 系统依赖、专用用户
ARG PUID=1000
ARG PGID=1000

RUN set -eux; \
    sed -i 's|http://deb.debian.org|https://mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://security.debian.org|https://mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        zlib1g-dev \
        libxml2-dev \
        libxslt-dev \
        pkg-config \
        libssl-dev \
        fonts-wqy-zenhei \
        fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && groupadd -g ${PGID} pcrbot \
    && useradd -u ${PUID} -g pcrbot -m -d /home/pcrbot -s /bin/bash pcrbot

WORKDIR /HoshinoBot
USER pcrbot

# 框架依赖（供构建 venv 与 stamp 过期时重建）
COPY requirements.txt ./requirements.txt

RUN set -eux; \
    python3 -m venv /home/pcrbot/.venv \
    && /home/pcrbot/.venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ --upgrade pip \
    && /home/pcrbot/.venv/bin/pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
    && /home/pcrbot/.venv/bin/pip install --no-cache-dir -r ./requirements.txt \
    && py_ver="$(/home/pcrbot/.venv/bin/python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')" \
    && . /etc/os-release \
    && echo "${py_ver}-${ID}-${VERSION_ID}" > /home/pcrbot/.venv-build-stamp

COPY docker/ /HoshinoBot/docker/
COPY install_deps.py /HoshinoBot/install_deps.py
COPY docker/bashrc-pcrbot /home/pcrbot/.bashrc

ENV TZ=Asia/Shanghai \
    VIRTUAL_ENV=/home/pcrbot/.venv \
    PATH="/home/pcrbot/.venv/bin:$PATH"

ENTRYPOINT ["/HoshinoBot/docker/start.sh"]

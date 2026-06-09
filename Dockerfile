FROM python:3.11-slim-trixie
EXPOSE 8080

# 1. 设置环境变量 (合并同类项)
ENV TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY fonts/ /usr/shared/fonts/chinese/

# 2. 系统层优化 (合并层、配置源、安装依赖、清理)
RUN set -eux; \
    sed -i 's|http://deb.debian.org|https://mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://security.debian.org|https://mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    # 更新并安装依赖
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        zlib1g-dev \
        libxml2-dev \
        libxslt-dev \
    # 清理 apt 缓存 (减小镜像体积)
    && rm -rf /var/lib/apt/lists/* \
    # 设置时区
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && pip install -i https://mirrors.aliyun.com/pypi/simple/ --upgrade pip \
    && pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/


# 4. 设置工作目录 (代码将挂载到此)
WORKDIR /HoshinoBot

COPY requirements.txt ./
COPY **/requirements.txt ./

# 3. 安装 Python 依赖 (利用缓存层加速构建)
RUN pip install --no-cache-dir -r requirements.txt && \
    find . -name "requirements.txt" -path "*/modules/*" -exec pip install --no-cache-dir -r {} \; && \
    pip list

# 5. 启动命令 (根据 docker inspect 结果调整)
CMD ["python3", "run.py"]

EXPOSE 8080
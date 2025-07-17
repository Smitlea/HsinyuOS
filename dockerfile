# 使用輕量化 Python 基底映像
FROM python:3.10-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=10



RUN pip install --upgrade pip
# 設定工作目錄
WORKDIR /app

# 安裝必要系統套件
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libmariadb-dev \
    libmariadb-dev-compat \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*


# 複製專案檔案到容器
COPY . .


RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 開放必要的 Port（視應用而定）
EXPOSE 5000

# 啟動指令
CMD ["python", "app.py"]
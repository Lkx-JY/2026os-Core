FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY src/ ./src/
COPY configs/ ./configs/

# 暴露端口
EXPOSE 8000

# 启动命令 (src.api:app 比 src.main:app 更直接)
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]

# 使用 Python 官方輕量鏡像
FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 設定環境變數
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 安裝系統相依套件 (基礎運行所需，包含 OpenCV 需要的函式庫)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案代碼
COPY . .

# 啟動命令
CMD ["python", "monitor.py"]

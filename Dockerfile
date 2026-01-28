# 使用 Python 官方輕量鏡像
FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 設定環境變數
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
# 預設 EasyOCR 模型存放路徑
ENV EASYOCR_MODULE_PATH /app/models

# 安裝系統相依套件 (OpenCV 與 EasyOCR 必要組件)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 建立模型目錄
RUN mkdir -p /app/models

# 1. 優先安裝 CPU 版 PyTorch (大幅縮減體積)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 2. 安裝其他 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 預下載 OCR 模型 (避免啟動時下載)
RUN python -c "import easyocr; reader = easyocr.Reader(['ch_tra', 'en'], model_storage_directory='/app/models')"

# 複製專案代碼
COPY . .

# 啟動命令
CMD ["python", "monitor.py"]

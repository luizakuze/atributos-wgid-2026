FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    xmlsec1 \
    libxml2 \
    libxmlsec1 \
    libxmlsec1-openssl \
    pkg-config \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]

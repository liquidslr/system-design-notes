FROM python:3.11-slim

WORKDIR /app

# 使用国内 PyPI 镜像并增加超时/重试，避免慢网络下索引请求失败导致构建中断
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt .
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]

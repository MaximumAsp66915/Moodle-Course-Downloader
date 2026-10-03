FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
# CPU-only torch keeps the image small (the captcha CNN runs fine on CPU).
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY . .

CMD ["python", "moodle_downloader.py"]

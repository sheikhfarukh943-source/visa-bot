FROM ://microsoft.com
WORKDIR /app
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
RUN playwright install chromium
COPY . .
EXPOSE 8080
CMD ["python3", "app.py"]

#Dockerfile
FROM python:3.10-slim

WORKDIR /app 

RUN apt-get update && apt-get install -y libgomp1 && rm -rf /var/lib/apt/lists/*


COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8000 

ENTRYPOINT ["uvicorn"]
CMD ["main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"]

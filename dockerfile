FROM python:slim
	
WORKDIR /app
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/*.py .

ENTRYPOINT [ "python", "main.py" ]
FROM python:slim
	
WORKDIR /app
COPY src/requirements.txt .
RUN pip3 install --upgrade --no-cache-dir -r requirements.txt
COPY src/*.py .

ENTRYPOINT [ "python", "main.py" ]
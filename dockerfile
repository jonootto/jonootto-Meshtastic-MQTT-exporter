FROM python:slim
	
WORKDIR /app
COPY src/requirements.txt .
RUN pip install -r requirements.txt
COPY src/main.py .

ENTRYPOINT [ "python", "main.py" ]
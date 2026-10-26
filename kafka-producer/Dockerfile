FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml .
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install . \
    && PYTHONPATH=/install/lib/python3.12/site-packages \
       python -m grpc_tools.protoc \
       -I./app/proto \
       -I/install/lib/python3.12/site-packages/grpc_tools/_proto \
       --python_out=./app/proto ./app/proto/saluteSpeech.proto \
    && cp ./app/proto/saluteSpeech_pb2.py \
       /install/lib/python3.12/site-packages/app/proto/saluteSpeech_pb2.py

FROM python:3.12-slim
WORKDIR /service
COPY --from=build /install /usr/local
COPY --from=build /build/app ./app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

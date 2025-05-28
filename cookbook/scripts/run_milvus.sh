docker run -d \
  -p 19530:19530 \
  -p 9091:9091 \
  -v milvus_data:/var/lib/milvus \
  -e OTEL_SDK_DISABLED=true \
  -e MILVUS_USER=ai \
  -e MILVUS_PASSWORD=ai \
  -e MILVUS_DB_NAME=ai \
  --name milvus \
  milvusdb/milvus:2.3.2 \
  milvus run standalone 
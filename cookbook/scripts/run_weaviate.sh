docker run -d \
        -p 8081:8081 \
        -p 50051:50051 \
        --name weaviate \
        cr.weaviate.io/semitechnologies/weaviate:1.28.4 

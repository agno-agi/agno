docker run -d ^
        -p 8080:8080 ^
        -p 50051:50051 ^
        --name weaviate ^
        cr.weaviate.io/semitechnologies/weaviate:1.28.4 
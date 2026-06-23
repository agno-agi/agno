import asyncio
import json
from hashlib import md5, sha256
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.databricks.settings import DatabricksSettings
from agno.filters import FilterExpr, get_filter_value, matches_filter_expr
from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.utils.log import log_debug, log_info, log_warning
from agno.utils.string import generate_id
from agno.vectordb.base import VectorDb
from agno.vectordb.search import SearchType


def _get_vector_search_client_cls():
    try:
        from databricks.vector_search.client import VectorSearchClient  # type: ignore[import-not-found,import-untyped]
    except ImportError as exc:
        raise ImportError(
            "`databricks-vectorsearch` not installed. Please install using `pip install databricks-vectorsearch`"
        ) from exc
    return VectorSearchClient


class DatabricksVectorDb(VectorDb):
    """Databricks Vector Search integration for agno knowledge bases.

    Note: Delete and exists operations use full index scans (O(N)) because the
    Databricks Vector Search SDK does not support filtered point lookups. For
    large indexes (>10k rows), these operations may be slow.
    """

    def __init__(
        self,
        *,
        endpoint_name: str,
        index_name: str,
        primary_key: str = "id",
        embedding_vector_column: str = "embedding",
        text_column: str = "content",
        name_column: str = "name",
        metadata_column: str = "meta_data",
        content_id_column: str = "content_id",
        content_hash_column: str = "content_hash",
        usage_column: str = "usage",
        embedder: Optional[Embedder] = None,
        embedding_dimension: Optional[int] = None,
        embedding_model_endpoint_name: Optional[str] = None,
        workspace_url: Optional[str] = None,
        host: Optional[str] = None,
        token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        azure_tenant_id: Optional[str] = None,
        azure_login_id: Optional[str] = None,
        schema: Optional[Dict[str, str]] = None,
        search_type: SearchType = SearchType.vector,
        scan_batch_size: int = 100,
        max_scan_rows: int = 50_000,
        upsert_batch_size: int = 100,
        hash_algorithm: str = "md5",
        disable_notice: bool = True,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
    ):
        if id is None:
            seed = f"{host or workspace_url or 'databricks'}#{endpoint_name}#{index_name}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            name=name or index_name,
            description=description,
            similarity_threshold=similarity_threshold,
        )

        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_warning("Embedder not provided, using OpenAIEmbedder as default.")

        self.embedder: Embedder = embedder
        self.embedding_dimension = embedding_dimension or self.embedder.dimensions

        self.endpoint_name = endpoint_name
        self.index_name = index_name
        self.primary_key = primary_key
        self.embedding_vector_column = embedding_vector_column
        self.text_column = text_column
        self.name_column = name_column
        self.metadata_column = metadata_column
        self.content_id_column = content_id_column
        self.content_hash_column = content_hash_column
        self.usage_column = usage_column
        self.embedding_model_endpoint_name = embedding_model_endpoint_name
        self.search_type = search_type
        self.scan_batch_size = scan_batch_size
        self.max_scan_rows = max_scan_rows
        self.upsert_batch_size = upsert_batch_size
        self.hash_algorithm = hash_algorithm
        self.disable_notice = disable_notice
        self.azure_tenant_id = azure_tenant_id
        self.azure_login_id = azure_login_id

        self.settings = DatabricksSettings.from_values(
            host=host,
            workspace_url=workspace_url,
            token=token,
            client_id=client_id,
            client_secret=client_secret,
        )

        self._auto_configure_index = (
            schema is None
            and primary_key == "id"
            and embedding_vector_column == "embedding"
            and text_column == "content"
            and name_column == "name"
            and metadata_column == "meta_data"
            and content_id_column == "content_id"
            and content_hash_column == "content_hash"
            and usage_column == "usage"
        )
        self._index_defaults_loaded = False
        self.schema = schema or self._default_schema()
        self.return_columns = [
            column_name for column_name in self.schema.keys() if column_name != self.embedding_vector_column
        ]

        self._client: Optional[Any] = None
        self._index: Optional[Any] = None

    def _default_schema(self) -> Dict[str, str]:
        return {
            self.primary_key: "string",
            self.embedding_vector_column: "array<float>",
            self.text_column: "string",
            self.name_column: "string",
            self.metadata_column: "string",
            self.content_id_column: "string",
            self.content_hash_column: "string",
            self.usage_column: "string",
        }

    @property
    def client(self):
        if self._client is None:
            client_cls = _get_vector_search_client_cls()
            client_kwargs: Dict[str, Any] = {
                "workspace_url": self.settings.workspace_url,
                "personal_access_token": self.settings.token,
                "service_principal_client_id": self.settings.client_id,
                "service_principal_client_secret": self.settings.client_secret,
                "disable_notice": self.disable_notice,
            }
            if self.azure_tenant_id is not None:
                client_kwargs["azure_tenant_id"] = self.azure_tenant_id
            if self.azure_login_id is not None:
                client_kwargs["azure_login_id"] = self.azure_login_id
            client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
            self._client = client_cls(**client_kwargs)
        return self._client

    @property
    def index(self):
        if self._index is None:
            self._index = self.client.get_index(endpoint_name=self.endpoint_name, index_name=self.index_name)
        return self._index

    def create(self) -> None:
        if self.exists():
            return
        if self.embedding_dimension is None:
            raise ValueError("embedding_dimension or embedder.dimensions must be set before creating an index.")

        created_index = self.client.create_direct_access_index(
            endpoint_name=self.endpoint_name,
            index_name=self.index_name,
            primary_key=self.primary_key,
            embedding_dimension=self.embedding_dimension,
            embedding_vector_column=self.embedding_vector_column,
            schema=self.schema,
            embedding_model_endpoint_name=self.embedding_model_endpoint_name,
        )
        self._index = created_index

        if created_index is not None and hasattr(created_index, "wait_until_ready"):
            created_index.wait_until_ready(verbose=False)

    async def async_create(self) -> None:
        await asyncio.to_thread(self.create)

    def exists(self) -> bool:
        return self.client.index_exists(endpoint_name=self.endpoint_name, index_name=self.index_name)

    async def async_exists(self) -> bool:
        return await asyncio.to_thread(self.exists)

    def drop(self) -> None:
        if self.exists():
            self.client.delete_index(endpoint_name=self.endpoint_name, index_name=self.index_name)
            self._index = None

    async def async_drop(self) -> None:
        await asyncio.to_thread(self.drop)

    def upsert_available(self) -> bool:
        return True

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        self.upsert(content_hash=content_hash, documents=documents, filters=filters)

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        await self.async_upsert(content_hash=content_hash, documents=documents, filters=filters)

    def upsert(
        self,
        content_hash: str,
        documents: List[Document],
        filters: Optional[Dict[str, Any]] = None,
        cleanup_stale: bool = True,
    ) -> None:
        if not documents:
            log_info("No documents to upsert")
            return

        self._ensure_index_defaults_loaded()
        rows = [self._row_from_document(document, content_hash, filters) for document in documents]
        new_primary_keys = {row[self.primary_key] for row in rows if self.primary_key in row}

        # Upsert in batches to avoid payload-too-large errors
        for i in range(0, len(rows), self.upsert_batch_size):
            self.index.upsert(rows[i : i + self.upsert_batch_size])

        # Optionally clean up stale rows with the same content_hash but different primary keys
        if cleanup_stale:
            try:
                stale_keys = [
                    row[self.primary_key]
                    for row in self._scan_all_rows()
                    if row.get(self.content_hash_column) == content_hash
                    and self.primary_key in row
                    and row[self.primary_key] not in new_primary_keys
                ]
                if stale_keys:
                    self.index.delete(primary_keys=stale_keys)
            except Exception as exc:
                log_warning(f"Failed to clean up stale rows for content_hash={content_hash}: {exc}")

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        await asyncio.to_thread(self.upsert, content_hash, documents, filters)

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    ) -> List[Document]:
        self._ensure_index_defaults_loaded()
        request_filters = self._build_provider_filters(filters)
        query_vector = self.embedder.get_embedding(query)
        if not query_vector:
            log_warning(f"Could not generate embedding for query: {query}")
            return []
        if self.embedding_dimension is None:
            self.embedding_dimension = len(query_vector)

        # Over-fetch when client-side filtering is active so we can still return `limit` results
        is_client_side_filter = isinstance(filters, list)
        fetch_limit = limit * 3 if is_client_side_filter else limit

        search_kwargs: Dict[str, Any] = {
            "columns": self.return_columns,
            "query_vector": query_vector,
            "num_results": fetch_limit,
            "filters": request_filters,
        }
        if self.similarity_threshold is not None:
            search_kwargs["score_threshold"] = self.similarity_threshold
        if self.search_type == SearchType.hybrid:
            search_kwargs["query_type"] = "HYBRID"
            search_kwargs["query_text"] = query
        else:
            search_kwargs["query_type"] = "ANN"

        response = self.index.similarity_search(**search_kwargs)
        rows, _ = self._extract_rows_and_cursor(response)
        filtered_rows = self._apply_client_side_filters(rows, filters)
        return self._documents_from_rows(filtered_rows[:limit])

    async def async_search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    ) -> List[Document]:
        return await asyncio.to_thread(self.search, query, limit, filters)

    def delete(self) -> bool:
        primary_keys = [row[self.primary_key] for row in self._scan_all_rows() if self.primary_key in row]
        if not primary_keys:
            return False
        self.index.delete(primary_keys=primary_keys)
        return True

    def delete_by_id(self, id: str) -> bool:
        if not self.id_exists(id):
            return False
        self.index.delete(primary_keys=[id])
        return True

    def delete_by_name(self, name: str) -> bool:
        return self._delete_rows_matching(lambda row: row.get(self.name_column) == name)

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return self._delete_rows_matching(lambda row: self._metadata_matches(self._row_metadata(row), metadata))

    def delete_by_content_id(self, content_id: str) -> bool:
        return self._delete_rows_matching(lambda row: row.get(self.content_id_column) == content_id)

    def name_exists(self, name: str) -> bool:
        return any(row.get(self.name_column) == name for row in self._scan_all_rows())

    async def async_name_exists(self, name: str) -> bool:
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        return any(str(row.get(self.primary_key)) == str(id) for row in self._scan_all_rows())

    def content_hash_exists(self, content_hash: str) -> bool:
        return any(row.get(self.content_hash_column) == content_hash for row in self._scan_all_rows())

    async def async_delete(self) -> bool:
        return await asyncio.to_thread(self.delete)

    async def async_delete_by_id(self, id: str) -> bool:
        return await asyncio.to_thread(self.delete_by_id, id)

    async def async_delete_by_name(self, name: str) -> bool:
        return await asyncio.to_thread(self.delete_by_name, name)

    async def async_delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(self.delete_by_metadata, metadata)

    async def async_delete_by_content_id(self, content_id: str) -> bool:
        return await asyncio.to_thread(self.delete_by_content_id, content_id)

    async def async_content_hash_exists(self, content_hash: str) -> bool:
        return await asyncio.to_thread(self.content_hash_exists, content_hash)

    async def async_id_exists(self, id: str) -> bool:
        return await asyncio.to_thread(self.id_exists, id)

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        # Use a scan that includes the embedding vector so it survives re-upsert
        rows_to_update: List[Dict[str, Any]] = []
        last_pk = None
        while True:
            try:
                response = self.index.scan(num_results=self.scan_batch_size, last_primary_key=last_pk)
            except Exception as exc:
                log_warning(f"Failed to scan for update_metadata: {exc}")
                break
            batch, next_pk = self._extract_rows_and_cursor(response)
            if not batch:
                break
            rows_to_update.extend(row for row in batch if row.get(self.content_id_column) == content_id)
            if next_pk is None or next_pk == last_pk:
                break
            last_pk = next_pk

        if not rows_to_update:
            log_debug(f"No rows found for content_id: {content_id}")
            return

        updated_rows = []
        for row in rows_to_update:
            updated_row = dict(row)
            merged_metadata = self._row_metadata(updated_row)
            merged_metadata.update(metadata)
            updated_row[self.metadata_column] = json.dumps(merged_metadata)
            updated_rows.append(updated_row)

        self.index.upsert(updated_rows)

    async def async_update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        await asyncio.to_thread(self.update_metadata, content_id, metadata)

    def optimize(self) -> None:
        pass

    def get_supported_search_types(self) -> List[str]:
        return [SearchType.vector.value, SearchType.hybrid.value]

    def _row_from_document(
        self, document: Document, content_hash: str, filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if document.embedding is None or len(document.embedding) == 0:
            document.embed(embedder=self.embedder)

        metadata = document.meta_data.copy() if document.meta_data else {}
        if filters:
            metadata.update(filters)

        content_for_hash = document.content or ""
        hash_fn = sha256 if self.hash_algorithm == "sha256" else md5
        base_id = document.id or hash_fn(content_for_hash.encode("utf-8", errors="surrogatepass")).hexdigest()[:32]
        primary_value = (
            base_id
            if document.id is not None
            else hash_fn(f"{base_id}_{content_hash}".encode("utf-8", errors="surrogatepass")).hexdigest()[:32]
        )

        row: Dict[str, Any] = {
            self.primary_key: primary_value,
            self.embedding_vector_column: document.embedding,
            self.text_column: document.content,
            self.name_column: document.name,
            self.metadata_column: json.dumps(metadata),
            self.content_id_column: document.content_id,
            self.content_hash_column: content_hash,
            self.usage_column: json.dumps(document.usage) if document.usage else None,
        }

        for key in self.schema.keys():
            if key in row or key == self.embedding_vector_column:
                continue
            if filters and key in filters:
                row[key] = filters[key]
            elif key in metadata:
                row[key] = metadata[key]

        # Strip None values: Databricks vector search SDK rejects null fields in upsert payloads
        return {key: value for key, value in row.items() if value is not None}

    def _build_provider_filters(
        self, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]]
    ) -> Optional[Dict[str, Any]]:
        if filters is None:
            return None
        if isinstance(filters, list):
            log_warning(
                "FilterExpr filters are not supported in DatabricksVectorDb. Falling back to client-side filtering."
            )
            return None

        if not isinstance(filters, dict):
            log_warning(f"Unsupported filter type: {type(filters).__name__}. Ignoring.")
            return None

        provider_filters: Dict[str, Any] = {}
        for key, value in filters.items():
            if key in self.schema and key not in {
                self.metadata_column,
                self.embedding_vector_column,
                self.usage_column,
            }:
                provider_filters[key] = value
        return provider_filters or None

    def _apply_client_side_filters(
        self, rows: List[Dict[str, Any]], filters: Optional[Union[Dict[str, Any], List[FilterExpr]]]
    ) -> List[Dict[str, Any]]:
        if filters is None:
            return rows
        if isinstance(filters, list):
            return [row for row in rows if all(matches_filter_expr(self._build_filterable_row(row), expr) for expr in filters)]
        return [row for row in rows if self._metadata_matches(self._build_filterable_row(row), filters)]

    def _metadata_matches(self, metadata: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        for key, value in filters.items():
            if get_filter_value(metadata, key) != value:
                return False
        return True

    def _documents_from_rows(self, rows: List[Dict[str, Any]]) -> List[Document]:
        documents: List[Document] = []
        for row in rows:
            meta_data = self._row_metadata(row)
            document = Document(
                id=str(row[self.primary_key]) if self.primary_key in row else None,
                name=row.get(self.name_column),
                content=row.get(self.text_column, ""),
                meta_data=meta_data,
                embedder=self.embedder,
                content_id=row.get(self.content_id_column),
            )
            score = row.get("score")
            if isinstance(score, (float, int)):
                document.reranking_score = float(score)
            documents.append(document)
        return documents

    def _build_filterable_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        metadata = self._row_metadata(row)
        filterable_row = dict(row)
        filterable_row[self.metadata_column] = metadata
        filterable_row.update(metadata)
        return filterable_row

    def _row_metadata(self, row: Dict[str, Any]) -> Dict[str, Any]:
        raw_metadata = row.get(self.metadata_column)
        if isinstance(raw_metadata, dict):
            return raw_metadata
        if isinstance(raw_metadata, str) and raw_metadata:
            try:
                parsed = json.loads(raw_metadata)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                log_warning("Failed to decode Databricks vector search metadata JSON.")

        metadata = {}
        for key in self.schema.keys():
            if key in {
                self.primary_key,
                self.embedding_vector_column,
                self.text_column,
                self.name_column,
                self.metadata_column,
                self.content_id_column,
                self.content_hash_column,
                self.usage_column,
            }:
                continue
            if key in row:
                metadata[key] = row[key]
        return metadata

    def _scan_all_rows(self) -> List[Dict[str, Any]]:
        """Scan all rows in the index. WARNING: O(N) -- avoid on large indexes."""
        rows: List[Dict[str, Any]] = []
        last_primary_key = None

        while True:
            response = self.index.scan(num_results=self.scan_batch_size, last_primary_key=last_primary_key)
            batch_rows, next_primary_key = self._extract_rows_and_cursor(response)
            if not batch_rows:
                break
            # Check stuck cursor BEFORE extending to avoid duplicates
            if next_primary_key is not None and next_primary_key == last_primary_key:
                rows.extend(batch_rows)
                break
            rows.extend(batch_rows)
            if next_primary_key is None:
                break
            if len(rows) >= self.max_scan_rows:
                log_warning(f"Scan reached max_scan_rows limit ({self.max_scan_rows}). Results may be incomplete.")
                break
            last_primary_key = next_primary_key

        return rows

    def _extract_rows_and_cursor(self, response: Any) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
        if isinstance(response, list):
            return self._normalize_rows(response, None), None
        if not isinstance(response, dict):
            return [], None

        result = response.get("result")
        if isinstance(result, dict):
            manifest = response.get("manifest") or result.get("manifest") or {}
            rows = result.get("data") or result.get("records")
            if rows is None and isinstance(result.get("data_array"), list):
                columns = self._manifest_columns(manifest)
                rows = [dict(zip(columns, item)) for item in result["data_array"] if isinstance(item, list)]
            cursor = (
                result.get("last_primary_key")
                or result.get("next_primary_key")
                or response.get("last_primary_key")
                or response.get("next_primary_key")
            )
            return self._normalize_rows(rows, manifest), cursor

        rows = response.get("data") or response.get("records") or response.get("results")
        cursor = response.get("last_primary_key") or response.get("next_primary_key")
        return self._normalize_rows(rows, response.get("manifest")), cursor

    def _manifest_columns(self, manifest: Any) -> List[str]:
        columns = manifest.get("columns", []) if isinstance(manifest, dict) else []
        column_names: List[str] = []
        for column in columns:
            if isinstance(column, dict) and "name" in column:
                column_names.append(column["name"])
            elif isinstance(column, str):
                column_names.append(column)
        return column_names

    def _normalize_rows(self, rows: Any, manifest: Any) -> List[Dict[str, Any]]:
        if rows is None:
            return []
        if isinstance(rows, list):
            if not rows:
                return []
            if all(isinstance(item, dict) for item in rows):
                if all("fields" in item for item in rows):
                    return [self._decode_struct_fields(item["fields"]) for item in rows if isinstance(item.get("fields"), list)]
                return list(rows)
            if all(isinstance(item, list) for item in rows):
                columns = self._manifest_columns(manifest)
                return [dict(zip(columns, item)) for item in rows]
        return []

    def _ensure_index_defaults_loaded(self) -> None:
        if self._index_defaults_loaded or not self._auto_configure_index:
            return

        try:
            description = self.index.describe()
        except Exception as exc:
            log_warning(f"Failed to describe Databricks vector search index for auto-configuration: {exc}")
            self._index_defaults_loaded = True
            return

        if isinstance(description, dict):
            described_primary_key = description.get("primary_key")
            if isinstance(described_primary_key, str) and described_primary_key:
                self.primary_key = described_primary_key

            delta_sync_spec = description.get("delta_sync_index_spec")
            if isinstance(delta_sync_spec, dict):
                embedding_source_columns = delta_sync_spec.get("embedding_source_columns")
                if isinstance(embedding_source_columns, list):
                    for column in embedding_source_columns:
                        if isinstance(column, dict) and isinstance(column.get("name"), str):
                            self.text_column = column["name"]
                            break

        sample_rows = self._sample_rows()
        if sample_rows:
            sample_row = sample_rows[0]
            self.embedding_vector_column = self._infer_embedding_column(sample_row) or self.embedding_vector_column
            self.schema = {column_name: self._infer_schema_type(value) for column_name, value in sample_row.items()}
            self.return_columns = [
                column_name for column_name in self.schema.keys() if column_name != self.embedding_vector_column
            ]

        self._index_defaults_loaded = True

    def _sample_rows(self) -> List[Dict[str, Any]]:
        try:
            response = self.index.scan(num_results=1)
        except Exception as exc:
            log_warning(f"Failed to sample Databricks vector search rows for auto-configuration: {exc}")
            return []

        rows, _ = self._extract_rows_and_cursor(response)
        return rows

    def _infer_embedding_column(self, row: Dict[str, Any]) -> Optional[str]:
        # Prefer the configured name if it exists and looks like an embedding
        if self.embedding_vector_column in row:
            value = row[self.embedding_vector_column]
            if isinstance(value, list) and value and all(isinstance(v, (int, float)) for v in value):
                return self.embedding_vector_column

        # Fall back to the longest numeric list
        best_col = None
        best_len = 0
        for key, value in row.items():
            if isinstance(value, list) and value and all(isinstance(v, (int, float)) for v in value):
                if len(value) > best_len:
                    best_col = key
                    best_len = len(value)
        return best_col

    def _infer_schema_type(self, value: Any) -> str:
        if isinstance(value, list):
            if value and all(isinstance(item, (int, float)) for item in value):
                return "array<float>"
            return "array<string>"
        if isinstance(value, dict):
            return "map<string,string>"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "long"
        if isinstance(value, float):
            return "double"
        return "string"

    def _decode_struct_fields(self, fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        decoded: Dict[str, Any] = {}
        for field in fields:
            key = field.get("key")
            value = field.get("value")
            if isinstance(key, str):
                decoded[key] = self._decode_databricks_value(value)
        return decoded

    def _decode_databricks_value(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "string_value" in value:
            return value["string_value"]
        if "number_value" in value:
            number = value["number_value"]
            if isinstance(number, float) and number.is_integer():
                return int(number)
            return number
        if "bool_value" in value:
            return value["bool_value"]
        if "null_value" in value:
            return None
        if "list_value" in value:
            list_value = value["list_value"]
            values = list_value.get("values", []) if isinstance(list_value, dict) else []
            return [self._decode_databricks_value(item) for item in values]
        if "struct_value" in value:
            struct_value = value["struct_value"]
            if isinstance(struct_value, dict):
                return self._decode_struct_fields(struct_value.get("fields", []))
        return value

    def _delete_rows_matching(self, predicate) -> bool:
        primary_keys = [
            row[self.primary_key] for row in self._scan_all_rows() if predicate(row) and self.primary_key in row
        ]
        if not primary_keys:
            return False
        self.index.delete(primary_keys=primary_keys)
        return True

    def _delete_by_content_hash(self, content_hash: str) -> bool:
        return self._delete_rows_matching(lambda row: row.get(self.content_hash_column) == content_hash)

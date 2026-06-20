import hashlib
import logging
import math
import os
from pathlib import Path
from typing import Any

from django.conf import settings

from apps.core.models import SystemConfig

logger = logging.getLogger(__name__)


class RuntimeConfigService:
    @staticmethod
    def _default(key: str, default: Any = None) -> Any:
        return getattr(settings, key, default)

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        value = cls._default(key, default)
        config = SystemConfig.objects.filter(key=key, is_active=True).first()
        return config.value if config else value


class EmbeddingService:
    def __init__(self) -> None:
        self.model_name = RuntimeConfigService.get("EMBEDDING_MODEL_ID", "sentence-transformers/all-MiniLM-L6-v2")
        self.batch_size = int(RuntimeConfigService.get("EMBEDDING_BATCH_SIZE", getattr(settings, "EMBEDDING_BATCH_SIZE", 32)))
        self.fallback_dim = int(
            RuntimeConfigService.get("EMBEDDING_FALLBACK_DIM", getattr(settings, "EMBEDDING_FALLBACK_DIM", 384))
        )
        self.local_files_only = bool(
            RuntimeConfigService.get(
                "EMBEDDING_LOCAL_FILES_ONLY",
                getattr(settings, "EMBEDDING_LOCAL_FILES_ONLY", False),
            )
        )
        self._model = None
        self.is_fallback = False
        self.vector_size: int | None = None

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name,
                local_files_only=self.local_files_only,
                trust_remote_code=False,
            )
            get_dim = getattr(self._model, "get_sentence_embedding_dimension", None)
            self.vector_size = int(get_dim()) if callable(get_dim) else None
            self.is_fallback = False
        except Exception as exc:
            logger.warning("Sentence transformer not available, fallback embedding used: %s", exc)
            self._model = None
            self.vector_size = self.fallback_dim
            self.is_fallback = True

    def _fallback_embedding(self, text: str, dim: int | None = None) -> list[float]:
        dim = dim or self.fallback_dim
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [digest[i % len(digest)] / 255.0 for i in range(dim)]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._load_model()
        if self._model is None:
            return [self._fallback_embedding(text, self.vector_size) for text in texts]
        vectors = self._model.encode(
            texts,
            batch_size=max(self.batch_size, 1),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [list(map(float, vector)) for vector in vectors]


class VectorStoreService:
    def __init__(self) -> None:
        self.collection = RuntimeConfigService.get("VECTOR_COLLECTION", "news_chunks")
        self.url = RuntimeConfigService.get("QDRANT_URL", os.getenv("QDRANT_URL", ""))
        self.api_key = RuntimeConfigService.get("QDRANT_API_KEY", os.getenv("QDRANT_API_KEY", ""))
        self.path = RuntimeConfigService.get("QDRANT_PATH", getattr(settings, "QDRANT_PATH", ""))
        self._client = None
        self._collection_ready = False
        self._vector_size: int | None = None

    def _connect(self) -> bool:
        if self._client is not None:
            return True
        try:
            from qdrant_client import QdrantClient

            if self.url:
                self._client = QdrantClient(url=self.url, api_key=self.api_key or None)
            elif self.path:
                storage_path = Path(str(self.path))
                if not storage_path.is_absolute():
                    storage_path = Path(settings.BASE_DIR) / storage_path
                storage_path.mkdir(parents=True, exist_ok=True)
                self._client = QdrantClient(path=str(storage_path))
            else:
                return False
            return True
        except Exception as exc:
            logger.warning("Qdrant unavailable, fallback DB retrieval used: %s", exc)
            self._client = None
            return False

    def _ensure_collection(self, vector_size: int) -> bool:
        if self._collection_ready and self._client is not None:
            return True
        if not self._connect():
            return False
        from qdrant_client.http import models as qmodels

        try:
            collection = self._client.get_collection(self.collection)
            self._vector_size = self._extract_vector_size(collection)
        except Exception:
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
            )
            self._vector_size = vector_size
        self._collection_ready = True
        return True

    @staticmethod
    def _extract_vector_size(collection: Any) -> int | None:
        config = getattr(collection, "config", None)
        params = getattr(config, "params", None)
        vectors = getattr(params, "vectors", None)
        size = getattr(vectors, "size", None)
        return int(size) if size else None

    def get_vector_size(self) -> int | None:
        if self._vector_size is not None:
            return self._vector_size
        if not self._connect():
            return None
        try:
            collection = self._client.get_collection(self.collection)
        except Exception:
            return None
        self._vector_size = self._extract_vector_size(collection)
        return self._vector_size

    def upsert(self, points: list[dict[str, Any]], vector_size: int) -> None:
        if not points:
            return
        if not self._ensure_collection(vector_size):
            return
        from qdrant_client.http import models as qmodels

        point_structs = [
            qmodels.PointStruct(
                id=point["id"],
                vector=point["vector"],
                payload=point.get("payload", {}),
            )
            for point in points
        ]
        self._client.upsert(collection_name=self.collection, points=point_structs)

    def search(self, vector: list[float], limit: int = 5, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self._connect():
            return []
        collection_vector_size = self.get_vector_size()
        if collection_vector_size is not None and len(vector) != collection_vector_size:
            logger.warning(
                "Qdrant search skipped because vector size %s does not match collection size %s.",
                len(vector),
                collection_vector_size,
            )
            return []
        try:
            query_filter = filters
            if filters:
                from qdrant_client.http import models as qmodels

                must_conditions = []
                for field, value in filters.items():
                    must_conditions.append(
                        qmodels.FieldCondition(key=field, match=qmodels.MatchValue(value=value))
                    )
                query_filter = qmodels.Filter(must=must_conditions)
            result = self._client.query_points(
                collection_name=self.collection,
                query=vector,
                limit=limit,
                query_filter=query_filter,
            )
            results = getattr(result, "points", result)
            output = []
            for item in results:
                output.append(
                    {
                        "id": item.id,
                        "score": float(item.score),
                        "payload": item.payload or {},
                    }
                )
            return output
        except Exception as exc:
            logger.warning("Qdrant search failed: %s", exc)
            return []

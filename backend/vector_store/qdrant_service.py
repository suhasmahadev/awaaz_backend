from qdrant_client import QdrantClient
from qdrant_client.http.models import VectorParams, Distance
from sentence_transformers import SentenceTransformer

COLLECTION = "carpulse_logs"

class QdrantService:
    _encoder = None  # singleton model

    def __init__(self):
        import os
        qdrant_url = os.getenv("QDRANT_URL")
        
        if qdrant_url:
            self.client = QdrantClient(url=qdrant_url)
        else:
            print("QDRANT_URL not set. Falling back to in-memory mode for deployment.")
            self.client = QdrantClient(":memory:")

        if QdrantService._encoder is None:
            QdrantService._encoder = SentenceTransformer("all-MiniLM-L6-v2")

        self.encoder = QdrantService._encoder

        collections = [c.name for c in self.client.get_collections().collections]
        if COLLECTION not in collections:
            self.client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )

    def embed(self, text: str):
        return self.encoder.encode(text).tolist()

    def upsert_log(self, log_id: str, text: str, payload: dict):
        vector = self.embed(text)

        self.client.upsert(
            collection_name=COLLECTION,
            points=[{
                "id": log_id,
                "vector": vector,
                "payload": payload
            }]
        )

    def semantic_search(self, query: str, limit: int = 5):
        vector = self.embed(query)

        return self.client.search(
            collection_name=COLLECTION,
            query_vector=vector,
            limit=limit
        )

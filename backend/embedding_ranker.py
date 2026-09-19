from sentence_transformers import SentenceTransformer
import numpy as np

try:
    from track_profile_builder import build_track_profile
except Exception:
    build_track_profile = None

class EmbeddingRanker:
    def __init__(self):
        self.cache = {}
        self.cache_limit = 10000
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
        self.device = device
        self.model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
        print(f"[embedding_ranker.init] device={self.device}")

    def build_text(self, track):
        if build_track_profile is not None:
            text = build_track_profile(track)
            if text:
                return text
        name = track.get("name", "")
        artist = track.get("artist", "")
        query = track.get("search_query", "")
        return f"{name} {artist} {query}"

    def rank(self, tracks, user_query, limit):
        if not tracks or limit <= 0:
            return []

        texts = [self.build_text(t) for t in tracks]
        query_text = user_query
        if not query_text:
            for track in tracks:
                candidate = track.get("search_query", "")
                if candidate:
                    query_text = candidate
                    break
        if not query_text:
            query_text = "music"

        track_embeddings = self.embed_texts_cached(texts)
        query_vec = self.embed_cached(query_text)
        if not track_embeddings or query_vec is None:
            return []

        try:
            track_vecs = np.vstack(track_embeddings)
        except ValueError:
            return []

        if track_vecs.ndim != 2 or query_vec.ndim != 1:
            return []
        if track_vecs.shape[0] != len(tracks) or track_vecs.shape[1] != query_vec.shape[0]:
            return []

        scores = np.dot(track_vecs, query_vec)

        ranked = sorted(zip(tracks, scores), key=lambda x: x[1], reverse=True)
        return [t for t, _ in ranked[:limit]]

    def embed_texts_cached(self, texts):
        uncached = []
        seen_uncached = set()
        for text in texts:
            if text not in self.cache and text not in seen_uncached:
                uncached.append(text)
                seen_uncached.add(text)

        if uncached:
            if len(self.cache) + len(uncached) > self.cache_limit:
                self.cache.clear()
            embeddings = self.model.encode(
                uncached,
                batch_size=32,
                normalize_embeddings=True,
            )
            for text, embedding in zip(uncached, embeddings):
                self.cache[text] = embedding

        return [self.cache[text] for text in texts]

    def embed_cached(self, text):
        return self.embed_texts_cached([text])[0]

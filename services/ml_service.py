from sentence_transformers import SentenceTransformer

_model = None

def get_embedding_model():
    """
    Lazy loads the SentenceTransformer model.
    This prevents the server from crashing during auto-reloads.
    """
    global _model
    if _model is None:
        print("⏳ Loading Embedding Model (this may take a moment)...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        print(" Embedding Model Loaded.")
    return _model
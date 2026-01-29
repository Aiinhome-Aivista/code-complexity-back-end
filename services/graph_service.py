import uuid
import logging
import chromadb
import itertools
import pandas as pd
from config import engine
from rapidfuzz import fuzz
from sqlalchemy import text
from sentence_transformers import SentenceTransformer

# Initialize ChromaDB & Model
chroma_client = chromadb.PersistentClient(path="./chroma_store")
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

def store_df_mysql(df, table_name):
    """Stores a DataFrame into MySQL and returns the safe table name."""
    safe_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in table_name)
    if isinstance(df, pd.DataFrame) and not df.empty:
        df.to_sql(safe_name, con=engine, if_exists='replace', index=False)
    return safe_name

def detect_relationships(dfs):
    """Identifies relationships between tables based on column name similarity."""
    relationships = []
    for (t1, df1), (t2, df2) in itertools.combinations(dfs.items(), 2):
        if not isinstance(df1, pd.DataFrame) or not isinstance(df2, pd.DataFrame):
            continue
            
        for c1 in df1.columns:
            for c2 in df2.columns:
                sim = fuzz.ratio(c1.lower(), c2.lower())
                if sim > 75:  # Threshold
                    relationships.append({
                        "table1": t1, "column1": c1,
                        "table2": t2, "column2": c2,
                        "similarity": sim
                    })
    return relationships

def generate_nodes(dfs):
    """Generates Node schemas (Node Edge/Age)."""
    nodes = []
    for t, df in dfs.items():
        # Differentiate between structured tables and unstructured docs
        cols = list(df.columns) if isinstance(df, pd.DataFrame) else []
        nodes.append({
            "label": t, 
            "props": {"columns": cols}
        })
    return nodes

def push_to_vector_db(uploaded_metadata, nodes, edges, session_id):
    """Pushes Metadata, Nodes, and Relationships to ChromaDB."""
    collection = chroma_client.get_or_create_collection(
        name=f"session_{session_id}",
        metadata={"hnsw:space": "cosine"}
    )

    documents = []
    embeddings = []
    ids = []

    # 1. File Metadata
    for meta in uploaded_metadata:
        text = f"File: {meta['filename']} stored as Table: {meta['table']}"
        documents.append(text)
        embeddings.append(embedding_model.encode(text).tolist())
        ids.append(str(uuid.uuid4()))

    # 2. Node Schemas
    for n in nodes:
        text = f"Node: {n['label']}, Columns: {n['props']['columns']}"
        documents.append(text)
        embeddings.append(embedding_model.encode(text).tolist())
        ids.append(str(uuid.uuid4()))

    # 3. Relationships
    for e in edges:
        text = f"Relationship: {e['table1']}.{e['column1']} -> {e['table2']}.{e['column2']}"
        documents.append(text)
        embeddings.append(embedding_model.encode(text).tolist())
        ids.append(str(uuid.uuid4()))

    collection.add(documents=documents, embeddings=embeddings, ids=ids)
    print(f"✅ ChromaDB updated for session {session_id}")

def save_graph_to_db(session_name, session_id, table_names, relationships):
    """Saves the generated graph structure to MySQL."""
    import json
    with engine.connect() as conn:
        # Using raw SQL as per your previous chat_new.py logic
        sql = text("""
        INSERT INTO session_tracking (session_name, session_id, tables, relationships)
        VALUES (:name, :id, :tables, :rels)
        ON DUPLICATE KEY UPDATE tables=VALUES(tables), relationships=VALUES(relationships)
        """)
        conn.execute(sql, {
            "name": session_name,
            "id": session_id,
            "tables": json.dumps(table_names),
            "rels": json.dumps(relationships)
        })
        conn.commit()
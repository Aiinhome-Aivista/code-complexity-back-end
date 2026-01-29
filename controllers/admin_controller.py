import os
import io
import uuid
import pypdf
import pandas as pd
from flask import request
from config import UPLOAD_FOLDER
from utils.response import api_response
from utils.file_utils import handle_zip_upload
from services.graph_service import (
    store_df_mysql, detect_relationships, generate_nodes, 
    push_to_vector_db, save_graph_to_db
)

def process_admin_upload():
    if 'files' not in request.files: return api_response("No files", None, 400)
    session_name = request.form.get("session_name")
    if not session_name: return api_response("Session Name Required", None, 400)

    files = request.files.getlist("files")
    session_id = str(uuid.uuid4())
    session_folder = os.path.join(UPLOAD_FOLDER, session_id)
    os.makedirs(session_folder, exist_ok=True)

    dfs = {}
    metadata = []

    def process(fname, content):
        ext = fname.rsplit('.', 1)[1].lower()
        df = None
        try:
            if ext == 'csv': df = pd.read_csv(io.BytesIO(content))
            elif ext in ['xls', 'xlsx']: df = pd.read_excel(io.BytesIO(content))
            elif ext == 'pdf':
                reader = pypdf.PdfReader(io.BytesIO(content))
                text = "\n".join([p.extract_text() or "" for p in reader.pages])
                if text.strip(): df = pd.DataFrame([{"document_text": text}])
            
            if df is not None:
                safe_name = store_df_mysql(df, f"{fname.split('.')[0]}_{uuid.uuid4().hex[:8]}")
                dfs[safe_name] = df
                metadata.append({"filename": fname, "table": safe_name})
        except Exception as e: print(f"Err {fname}: {e}")

    for f in files:
        if f.filename.endswith('.zip'):
            p = os.path.join(session_folder, f.filename)
            f.save(p)
            paths = handle_zip_upload(p, os.path.join(session_folder, "extracted"))
            for fp in paths:
                with open(fp, "rb") as subf: process(os.path.basename(fp), subf.read())
        else:
            process(f.filename, f.read())

    if not dfs: return api_response("No valid data", None, 400)

    rels = detect_relationships(dfs)
    nodes = generate_nodes(dfs)
    push_to_vector_db(metadata, nodes, rels, session_id)
    save_graph_to_db(session_name, session_id, list(dfs.keys()), rels)

    return api_response("Pipeline Complete", {"session_id": session_id, "nodes": len(nodes)}, 200)
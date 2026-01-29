import os
import re
from arango import ArangoClient
from pyvis.network import Network
from config import ARANGO_HOST, ARANGO_USER, ARANGO_PASS, ARANGO_DB

# Initialize Client
client = ArangoClient(hosts=ARANGO_HOST)

def get_db():
    sys_db = client.db('_system', username=ARANGO_USER, password=ARANGO_PASS)
    if not sys_db.has_database(ARANGO_DB):
        sys_db.create_database(ARANGO_DB)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASS)

def sanitize_key(key):
    """Sanitizes string to be a valid ArangoDB _key"""
    if not key: return "unknown"
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', str(key))

def init_session_graph(session_id):
    db = get_db()
    graph_name = f"session_{session_id}"
    
    if not db.has_graph(graph_name):
        db.create_graph(graph_name)

    graph = db.graph(graph_name)
    v_col = f"files_{session_id}"
    e_col = f"edges_{session_id}"

    if not graph.has_vertex_collection(v_col):
        graph.create_vertex_collection(v_col)
    
    if not graph.has_edge_definition(e_col):
        graph.create_edge_definition(
            edge_collection=e_col,
            from_vertex_collections=[v_col],
            to_vertex_collections=[v_col]
        )
    return graph, v_col, e_col

def store_graph_data(session_id, files_data, relationships):
    try:
        db = get_db()
        graph, v_col_name, e_col_name = init_session_graph(session_id)
        v_col = graph.vertex_collection(v_col_name)
        e_col = graph.edge_collection(e_col_name)

        # 1. Insert Nodes
        batch_vertices = []
        for f in files_data:
            raw_key = f.get('filename') or str(f.get('id'))
            key = sanitize_key(raw_key)
            
            batch_vertices.append({
                "_key": key,
                "label": f.get('filename', 'Unknown').split('/')[-1],
                "filename": f.get('filename', 'Unknown'),
                "folder": f.get('folder', 'Root'),
                "lines": f.get('lines_of_code', 0),
                "risk": f.get('risk_score', 0)
            })
        if batch_vertices: 
            v_col.import_bulk(batch_vertices, on_duplicate="update")

        # 2. Insert Edges
        batch_edges = []
        for rel in relationships:
            src = sanitize_key(rel['source'])
            tgt = sanitize_key(rel['target'])
            edge_key = sanitize_key(f"{src}_to_{tgt}")
            
            batch_edges.append({
                "_key": edge_key,
                "_from": f"{v_col_name}/{src}",
                "_to": f"{v_col_name}/{tgt}",
                "type": rel.get('type', 'dependency')
            })
        if batch_edges: 
            e_col.import_bulk(batch_edges, on_duplicate="ignore")
            
        print(f" ArangoDB Stored: {len(batch_vertices)} Nodes, {len(batch_edges)} Edges")
        return True
    except Exception as e:
        print(f" ArangoDB Store Error: {e}")
        return False

def generate_graph_html(session_id, output_path):
    """ Generates Interactive Graph HTML file using Pyvis """
    try:
        db = get_db()
        v_col_name = f"files_{session_id}"
        e_col_name = f"edges_{session_id}"
        
        if not db.has_collection(v_col_name): return False

        # Initialize Network with UTF-8 support context
        net = Network(height="750px", width="100%", bgcolor="#0b1120", font_color="white", cdn_resources='in_line')
        
        # Add Nodes
        cursor_nodes = db.aql.execute(f"FOR doc IN `{v_col_name}` RETURN doc")
        for node in cursor_nodes:
            color = "#97c2fc"
            grp = (node.get('folder') or 'root').lower()
            if 'controller' in grp: color = "#10b981"
            elif 'model' in grp: color = "#f472b6"
            elif 'db' in grp: color = "#3b82f6"
            elif 'view' in grp: color = "#a855f7"
            
            net.add_node(
                node["_key"], 
                label=node.get("label", "?"), 
                title=f"File: {node.get('filename')}\nLines: {node.get('lines', 0)}", 
                color=color, shape='dot', size=20 + (node.get('risk', 0) / 5)
            )

        # Add Edges
        if db.has_collection(e_col_name):
            cursor_edges = db.aql.execute(f"FOR doc IN `{e_col_name}` RETURN doc")
            for edge in cursor_edges:
                src = edge["_from"].split('/')[1]
                tgt = edge["_to"].split('/')[1]
                net.add_edge(src, tgt, color="#555555", arrows="to")

        net.set_options("""
        var options = {
          "physics": {
            "forceAtlas2Based": { "gravitationalConstant": -50, "springLength": 100 },
            "minVelocity": 0.75, "solver": "forceAtlas2Based"
          }
        }
        """)

        # FIX: Explicit UTF-8 encoding to prevent charmap error on Windows
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        html_content = net.generate_html()
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        print(f"✅ Graph HTML saved: {output_path}")
        return True
    except Exception as e:
        print(f"❌ Graph Generation Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_graph_from_arango(session_id):
    try:
        db = get_db()
        v_col = f"files_{session_id}"
        e_col = f"edges_{session_id}"
        if not db.has_collection(v_col): return {"files": [], "relationships": []}

        files = [{
            "id": doc["_key"],
            "filename": doc["filename"],
            "lines_of_code": doc.get("lines", 0),
            "risk_score": doc.get("risk", 0),
            "folder": doc.get("folder", "Root")
        } for doc in db.aql.execute(f"FOR doc IN `{v_col}` RETURN doc")]

        rels = []
        if db.has_collection(e_col):
            rels = [{
                "source": doc["_from"].split('/')[1],
                "target": doc["_to"].split('/')[1]
            } for doc in db.aql.execute(f"FOR doc IN `{e_col}` RETURN doc")]

        return {"files": files, "relationships": rels}
    except Exception:
        return {"files": [], "relationships": []}
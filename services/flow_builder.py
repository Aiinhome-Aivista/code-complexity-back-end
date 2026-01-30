import re

# -----------------------------
# Utils
# -----------------------------

PYTHON_BUILTINS = {
    "len", "print", "isinstance", "jsonify", "dict", "list",
    "set", "int", "str", "float", "bool", "range"
}


def generate_node_id(name: str) -> str:
    """
    Generates a stable, frontend-safe node id
    """
    return re.sub(r'[^a-zA-Z0-9]', '_', name).lower()


def auto_position(index, cols=3, x_start=900, y_start=80, x_gap=300, y_gap=200):
    row = index // cols
    col = index % cols
    return (
        x_start + col * x_gap,
        y_start + row * y_gap
    )

# -----------------------------
# Category detection
# -----------------------------

def infer_category(folder: str, filename: str) -> str:
    text = f"{folder}/{filename}".lower()

    rules = {
        "api": ["controller", "route", "endpoint", "app.py", "main.py"],
        "component": ["component", "view", "ui", "screen", "page"],
        "model": ["model", "entity", "schema", "dto"],
        "util": ["util", "helper", "common", "shared"],
        "config": ["config", "setting", "env"]
    }

    for category, keywords in rules.items():
        if any(k in text for k in keywords):
            return category

    return "util"

# -----------------------------
# Field extraction
# -----------------------------

def extract_fields(content: str):
    fields = []
    seen = set()

    function_patterns = [
        r'def\s+(\w+)\(',
        r'function\s+(\w+)\(',
        r'(?:public|private|protected)?\s*\w+\s+(\w+)\(',
    ]

    for pattern in function_patterns:
        for name in re.findall(pattern, content):
            if name in PYTHON_BUILTINS:
                continue

            key = f"{name}()"
            if key not in seen:
                seen.add(key)
                fields.append({"name": key, "type": "function"})

    state_patterns = [
        r'this\.(\w+)\s*=',
        r'(\w+)\s*=\s*None',
        r'let\s+(\w+)\s*=',
        r'const\s+(\w+)\s*='
    ]

    for pattern in state_patterns:
        for name in re.findall(pattern, content):
            if name not in seen:
                seen.add(name)
                fields.append({"name": name, "type": "state"})

    return fields[:8]

# -----------------------------
# Dependency extraction (PROJECT-ONLY)
# -----------------------------

def get_project_file_ids(files_data):
    """
    Collect all valid project file node ids
    """
    return {
        generate_node_id(f["filename"])
        for f in files_data
        if f.get("filename")
    }


def extract_dependencies_from_content(content: str, project_file_ids):
    deps = set()

    patterns = [
        r'import\s+([\w\.]+)',
        r'from\s+([\w\.]+)\s+import',
        r'require\([\'"](.+?)[\'"]\)',
        r'import\s+.*?from\s+[\'"](.+?)[\'"]'
    ]

    for pattern in patterns:
        for match in re.findall(pattern, content):
            base = match.split("/")[-1].split(".")[-1]
            dep_id = generate_node_id(base + ".py")

            # ✅ KEEP ONLY PROJECT FILES
            if dep_id in project_file_ids:
                deps.add(dep_id)

    return list(deps)


# -----------------------------
# MAIN BUILDER
# -----------------------------

def build_flow_nodes(files_data, relationships=None):
    nodes = []
    project_file_ids = get_project_file_ids(files_data)

    for index, f in enumerate(files_data):
        filename = f.get("filename")
        if not filename:
            continue

        node_id = generate_node_id(filename)
        x, y = auto_position(index)

        nodes.append({
            "id": node_id,
            "name": filename,
            "type": "file",
            "category": infer_category(
                f.get("folder", ""),
                filename
            ),
            "x": x,
            "y": y,
            "fields": extract_fields(
                f.get("content", "")
            ),
            "dependencies": extract_dependencies_from_content(
                f.get("content", ""),
                project_file_ids
            )
        })

    return nodes



import os
import zipfile

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {
        'py', 'js', 'ts', 'tsx', 'zip', 'java', 'cpp', 'c', 'h', 'css', 'html', 'json', 'csv', 'xlsx', 'xls', 'pdf'
    }

def handle_zip_upload(zip_path, extract_to_folder):
    os.makedirs(extract_to_folder, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to_folder)
    
    file_paths = []
    for root, dirs, files in os.walk(extract_to_folder):
        for file in files:
            if file.startswith('.') or file.startswith('__MACOSX'): continue
            if allowed_file(file):
                file_paths.append(os.path.join(root, file))
    return file_paths
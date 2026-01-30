import os
import shutil
from config import UPLOAD_FOLDER
from flask import request, send_file
from utils.response import api_response


def download_updated_code():
    """
    Zips the current state of the 'extracted' folder and sends it to the user.
    Usage: GET /api/download_updated_code?user_id=1&session_id=abc-123
    """
    # 1. Get params from URL Query String
    user_id = request.args.get('user_id')
    session_id = request.args.get('session_id')

    if not user_id or not session_id:
        return api_response("Missing user_id or session_id", None, 400)

    # 2. Define Paths
    session_root = os.path.join(UPLOAD_FOLDER, str(user_id), session_id)
    
    # This points to: uploads/1/abc-123/extracted/ (Where the fixed code lives)
    extracted_folder = os.path.join(session_root, "extracted")
    
    zip_filename = f"updated_project_{session_id}"
    zip_file_path = os.path.join(session_root, zip_filename)

    # 3. Check if we have code to zip
    if not os.path.exists(extracted_folder):
        return api_response("No code found to download. Please upload and analyze first.", None, 404)

    try:
        # 4. Create the Zip File
        shutil.make_archive(zip_file_path, 'zip', root_dir=extracted_folder)
        
        # shutil.make_archive adds the extension automatically, so we append it for the path
        final_zip_path = zip_file_path + ".zip"

        # 5. Send the file to the user
        return send_file(
            final_zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"fixed_code_{session_id}.zip"
        )

    except Exception as e:
        print(f"Download Error: {e}")
        return api_response("Failed to generate zip file", str(e), 500)
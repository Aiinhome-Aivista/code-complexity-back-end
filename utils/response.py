from flask import jsonify

def api_response(message, data=None, status_code=200, is_success=None):
    if is_success is None:
        is_success = 200 <= status_code < 300

    response = {
        "statuscode": status_code,
        "isSuccess": is_success,
        "message": message,
        "data": data
    }
    return jsonify(response), status_code
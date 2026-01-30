from models import db, Project, Upload
from utils.response import api_response
from flask import Flask, request, jsonify
from services.flow_builder import build_flow_nodes
from services.ai_flow_refiner import refine_flow_with_ai


def get_relationship_flow():
    try:
        data = request.get_json()

        project_id = data.get("project_id")
        session_id = data.get("session_id")

        if not project_id or not session_id:
            return api_response(
                "project_id and session_id are required",
                None,
                400
            )

        # 1️⃣ Fetch project
        project = db.session.get(Project, project_id)
        if not project:
            return api_response("Project not found", None, 404)

        # 2️⃣ Fetch upload entry
        upload = Upload.query.filter_by(
            project_id=project_id,
            session_id=session_id
        ).first()

        if not upload:
            return api_response("Upload data not found", None, 404)

        # 3️⃣ If already generated → return cached data
        if (
            project.relationship_status == "DONE"
            and upload.relationships
            and len(upload.relationships) > 0
        ):
            return api_response(
                "Relationship fetched from cache",
                upload.relationships,
                200
            )

        # 4️⃣ Mark PENDING
        project.relationship_status = "PENDING"
        db.session.commit()

        # 5️⃣ Generate static relationships
        flow_nodes = build_flow_nodes(
            files_data=upload.files,
            relationships=upload.relationships
        )

        # AI REFINEMENT (NEW)
        flow_nodes = refine_flow_with_ai(
            flow_nodes=flow_nodes,
            files_data=upload.files
        )

        # 6️⃣ Save generated relationships
        upload.relationships = flow_nodes
        project.relationship_status = "DONE"

        db.session.commit()

        return api_response(
            "Relationship generated successfully",
            flow_nodes,
            200
        )

    except Exception as e:
        db.session.rollback()

        # keep project in pending if failure
        if project_id:
            project = db.session.get(Project, project_id)
            if project:
                project.relationship_status = "PENDING"
                db.session.commit()

        return api_response(
            f"Relationship generation failed: {str(e)}",
            None,
            500
        )



from flask import Blueprint, request, jsonify
import subprocess
import json

run_script_bp = Blueprint('run_script', __name__)

@run_script_bp.route('/run-script', methods=['POST'])
def run_script():
    data = request.get_json()
    company = data.get("companyName")
    row_meta = data.get("rowMeta")
    base_url = data.get("baseUrl")
    page_numbers = data.get("pageNumbers")

    # Pass all as JSON string to scraper
    try:
        subprocess.run(
            [
                "python", "codal_scraper.py",
                company,
                str(row_meta),
                base_url,
                json.dumps(page_numbers)
            ],
            check=True
        )
        return jsonify({"message": "Script executed successfully!"})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Script error: {str(e)}"}), 500

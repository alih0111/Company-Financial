from flask import Blueprint, request, jsonify
import json
import subprocess
import pyodbc

bulk_fetch_bp = Blueprint('bulk_fetch', __name__)

# Reuse this connection string or import it from a config module
connection_string = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=wsn-mis-068;'
    'DATABASE=codal;'
    'UID=sa;'
    'PWD=dbco@2023hamkaran'
)

def get_url_from_db(company_name, script):
    table = "miandore2" if script == "script1" else "mahane"
    query = f"SELECT TOP 1 Url FROM {table} WHERE CompanyName LIKE ?"

    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (company_name,))
        row = cursor.fetchone()
        return row.Url if row else ""

@bulk_fetch_bp.route('/api/fetchAllData', methods=['POST'])
def fetch_all_data():
    data = request.get_json()
    script = data.get("script")  # "script1" or "script2"
    companies = data.get("companies", [])
    row_meta = data.get("rowMeta", 20)
    page_numbers = data.get("pageNumbers", [1, 2, 3, 4])

    if not companies or script not in ["script1", "script2"]:
        return jsonify({"error": "Invalid input"}), 400

    errors = []

    for company in companies:
        try:
            url = get_url_from_db(company, script)
            if not url:
                errors.append(f"No URL found for {company}")
                continue

            subprocess.run(
                [
                    "python",
                    f"codal_scraper{'' if script == 'script1' else '2'}.py",
                    company,
                    str(row_meta),
                    url,
                    json.dumps(page_numbers),
                ],
                check=True
            )
        except subprocess.CalledProcessError as e:
            errors.append(f"{company} failed: {str(e)}")

    if errors:
        return jsonify({"message": "Partial success", "errors": errors}), 207
    return jsonify({"message": "All scripts executed successfully"}), 200

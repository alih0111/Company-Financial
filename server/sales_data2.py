from flask import Blueprint, jsonify, request
import pyodbc

sales_data2_bp = Blueprint('sales_data2', __name__)

connection_string = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=wsn-mis-068;'
    'DATABASE=codal;'
    'UID=sa;'
    'PWD=dbco@2023hamkaran'
)

@sales_data2_bp.route('/api/SalesData2', methods=['GET'])
def get_sales_data():
    company_name = request.args.get('companyName')
    query = "SELECT CompanyName, CompanyID, ReportDate, Value1, Value2, Value3 FROM mahane"
    params = ()

    if company_name:
        query += " WHERE CompanyName = ?"
        params = (company_name,)

    data = []
    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        for row in cursor.fetchall():
            value1, value2, value3 = float(row.Value1), float(row.Value2), float(row.Value3)
            if value1 == 0:
                continue            
        
            data.append({
                "companyName": row.CompanyName,
                "companyID": row.CompanyID,
                "reportDate": row.ReportDate,
                "value1": value1/1000000,
                "value2": value2/1000000,
                "value3": value3/1000000,
                "percentage": value3/1000,
                "wow": 1 if (value1 > 0 and (value2 < 0 or value3 < 0)) else (-1 if (value1 < 0 and (value2 > 0 or value3 > 0)) else 0)
            })

    return jsonify(data)

@sales_data2_bp.route('/api/GetUrl2', methods=['POST'])
def get_url():
    data = request.get_json()
    company_name = data.get("companyName")

    query = "SELECT TOP 1 Url FROM mahane WHERE CompanyName like ?"

    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (company_name,))
        row = cursor.fetchone()
        if row:
            return jsonify({"url": row.Url})
        else:
            return jsonify({"url": ""})


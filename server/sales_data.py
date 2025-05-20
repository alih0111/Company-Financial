from flask import Blueprint, jsonify, request
import pyodbc

sales_data_bp = Blueprint('sales_data', __name__)

connection_string = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=wsn-mis-068;'
    'DATABASE=codal;'
    'UID=sa;'
    'PWD=dbco@2023hamkaran'
)

@sales_data_bp.route('/api/SalesData', methods=['GET'])
def get_sales_data():
    company_name = request.args.get('companyName')
    query = "SELECT CompanyName, CompanyID, ReportDate, Value1, Value2, Value3 FROM miandore"
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
            pct = (value1 / value2 if value2 != 0 else value1 / value3) * 100 

            if value1 < 0 and value2 < 0 and value1 < value2:
                pct *= -1
            elif value1 > 0 and value2 < 0:
                pct *= -1
            elif value2 == 0:
                if value1 < 0 and value3 < 0 and value1 < value3:
                    pct *= -1
                if value1 > 0 and value3 < 0:
                    pct *= -1

            if(pct>0):
                pct -= 100

            data.append({
                "companyName": row.CompanyName,
                "companyID": row.CompanyID,
                "reportDate": row.ReportDate,
                "value1": value1,
                "value2": value2,
                "value3": value3,
                "percentage": round(pct, 2),
                "wow": 1 if (value1 > 0 and (value2 < 0 or value3 < 0)) else (-1 if (value1 < 0 and (value2 > 0 or value3 > 0)) else 0)
            })

    return jsonify(data)


@sales_data_bp.route('/api/CompanyNames', methods=['GET'])
def get_company_names():
    query = "SELECT DISTINCT CompanyName FROM miandore"
    company_names = []
    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        for row in cursor.fetchall():
            company_names.append(row.CompanyName)
    return jsonify(company_names)



@sales_data_bp.route('/api/GetUrl', methods=['POST'])
def get_url():
    data = request.get_json()
    company_name = data.get("companyName")

    query = "SELECT TOP 1 Url FROM miandore WHERE CompanyName like ?"

    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (company_name,))
        row = cursor.fetchone()
        if row:
            return jsonify({"url": row.Url})
        else:
            return jsonify({"url": ""})


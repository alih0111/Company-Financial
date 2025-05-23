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
    query = "SELECT CompanyName, CompanyID, ReportDate, Product1, Product2, Product3 FROM miandore2"
    params = ()

    if company_name:
        query += " WHERE CompanyName = ?"
        params = (company_name,)

    data = []
    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        for row in cursor.fetchall():
            Product1, Product2, Product3 = float(row.Product1), float(row.Product2), float(row.Product3)
            if Product1 == 0:
                continue
            # pct = (Product1 / Product2 if Product2 != 0 else Product1 / Product3) * 100 

            # if Product1 < 0 and Product2 < 0 and Product1 < Product2:
            #     pct *= -1
            # elif Product1 > 0 and Product2 < 0:
            #     pct *= -1
            # elif Product2 == 0:
            #     if Product1 < 0 and Product3 < 0 and Product1 < Product3:
            #         pct *= -1
            #     if Product1 > 0 and Product3 < 0:
            #         pct *= -1

            pct=Product1/1000000

            # if(pct>0):
            #     pct -= 100

            data.append({
                "companyName": row.CompanyName,
                "companyID": row.CompanyID,
                "reportDate": row.ReportDate,
                "Product1": Product1,
                "Product2": Product2,
                "Product3": Product3,
                "percentage": round(pct, 2),
                "wow": 1 if (Product1 > 0 and (Product2 < 0 or Product3 < 0)) else (-1 if (Product1 < 0 and (Product2 > 0 or Product3 > 0)) else 0)
            })

    return jsonify(data)


@sales_data_bp.route('/api/CompanyNames', methods=['GET'])
def get_company_names():
    query = "SELECT DISTINCT CompanyName FROM miandore2"
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

    query = "SELECT TOP 1 Url FROM miandore2 WHERE CompanyName like ?"

    with pyodbc.connect(connection_string) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (company_name,))
        row = cursor.fetchone()
        if row:
            return jsonify({"url": row.Url})
        else:
            return jsonify({"url": ""})


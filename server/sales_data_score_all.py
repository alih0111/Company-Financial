from flask import Blueprint, jsonify, request
import pyodbc
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler

scoreAll_bp = Blueprint('scoreAll', __name__)

connection_string = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=wsn-mis-068;'
    'DATABASE=codal;'
    'UID=sa;'
    'PWD=dbco@2023hamkaran'
)

@scoreAll_bp.route('/api/AllCompanyScores', methods=['GET'])
def get_company_scores():
    # 1. Load sales and EPS data for all companies
    # sales_query = "SELECT CompanyID, CompanyName, ReportDate, Value1, Value2, Value3 FROM mahane"
    eps_query = "SELECT CompanyID, CompanyName, ReportDate, Product1, Product2, Product3 FROM miandore2"

    with pyodbc.connect(connection_string) as conn:
        # sales_df = pd.read_sql(sales_query, conn)
        eps_df = pd.read_sql(eps_query, conn)

    # if sales_df.empty or eps_df.empty:
    #     return jsonify({"error": "No data found"}), 404

    # 2. Preprocess
    # sales_df['Sales'] = sales_df[['Value3']].sum(axis=1)
    eps_df['EPS'] = eps_df[['Product1']].mean(axis=1)

    # sales_df = sales_df[['CompanyID', 'CompanyName', 'ReportDate', 'Sales']]
    eps_df = eps_df[['CompanyID', 'ReportDate', 'EPS', 'CompanyName']]

    # 3. Pivot tables
    # sales_pivot = sales_df.pivot(index='ReportDate', columns='CompanyID', values='Sales')
    eps_pivot = eps_df.pivot(index='ReportDate', columns='CompanyID', values='EPS')

    # 4. Score calculation
    scores = {}
    for company in eps_pivot.columns:
        eps_series = eps_pivot.get(company, pd.Series()).dropna().sort_index()

        eps_level = eps_series.mean()

        # EPS growth (compare recent 4 to previous 4)
        eps_growth = 0
        if len(eps_series) >= 8:
            recent_eps = eps_series[-4:].mean()
            prev_year_eps = eps_series[-8:-4].mean()
            if prev_year_eps != 0:
                eps_growth = (recent_eps - prev_year_eps) / abs(prev_year_eps) * 100
                eps_growth = round(eps_growth, 2)


        scores[company] = {
            'EPSGrowth': eps_growth
        }

    if not scores:
        return jsonify({"error": "No valid score data"}), 400

    # 5. Normalize scores
    score_df = pd.DataFrame(scores).T.fillna(0)
    scaler = MinMaxScaler()
    normalized = pd.DataFrame(
        scaler.fit_transform(score_df),
        columns=score_df.columns,
        index=score_df.index
    )

    result = []
    for company_id in normalized.index:
        company_rows = eps_df[eps_df['CompanyID'] == company_id]
        company_name_val = company_rows['CompanyName'].iloc[0] if not company_rows.empty else None

        result.append({
            "companyID": company_id,
            "companyName": company_name_val,
            "epsGrowth": round(score_df.loc[company_id, 'EPSGrowth'], 4),
        })
    result.sort(key=lambda x: x['epsGrowth'], reverse=True)
    # result = sorted(result, key=lambda x: x['finalScore'], reverse=True)
    return jsonify(result)

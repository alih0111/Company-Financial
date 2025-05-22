from flask import Blueprint, jsonify, request
import pyodbc
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler

score_bp = Blueprint('score', __name__)

connection_string = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=wsn-mis-068;'
    'DATABASE=codal;'
    'UID=sa;'
    'PWD=dbco@2023hamkaran'
)

@score_bp.route('/api/CompanyScores', methods=['GET'])
def get_company_scores():
    company_name = request.args.get('companyName')

    # 1. Load sales and EPS data
    sales_query = "SELECT CompanyID, CompanyName, ReportDate, Value1, Value2, Value3 FROM mahane"
    eps_query = "SELECT CompanyID, CompanyName, ReportDate, Value1, Value2, Value3 FROM miandore"

    params = ()
    if company_name:
        sales_query += " WHERE CompanyName LIKE ?"
        eps_query += " WHERE CompanyName LIKE ?"
        params = (f"%{company_name}%",)

    with pyodbc.connect(connection_string) as conn:
        sales_df = pd.read_sql(sales_query, conn, params=params)
        eps_df = pd.read_sql(eps_query, conn, params=params)

    if sales_df.empty or eps_df.empty:
        return jsonify({"error": "No data found"}), 404

    # 2. Preprocess
    sales_df['Sales'] = sales_df[['Value3']].sum(axis=1)
    eps_df['EPS'] = eps_df[['Value1']].mean(axis=1)

    sales_df = sales_df[['CompanyID', 'CompanyName', 'ReportDate', 'Sales']]
    eps_df = eps_df[['CompanyID', 'ReportDate', 'EPS']]

    # 3. Pivot tables
    sales_pivot = sales_df.pivot(index='ReportDate', columns='CompanyID', values='Sales')
    eps_pivot = eps_df.pivot(index='ReportDate', columns='CompanyID', values='EPS')

    # 4. Score calculation
    scores = {}
    for company in sales_pivot.columns:
        sales_series = sales_pivot[company].dropna().sort_index()
        eps_series = eps_pivot.get(company, pd.Series()).dropna().sort_index()

        if sales_series.empty or eps_series.empty:
            continue

        sales_growth = sales_series.pct_change().mean()
        sales_stability = 1 - (sales_series.std() / sales_series.mean()) if sales_series.mean() else 0
        eps_level = eps_series.mean()
        eps_growth = eps_series.pct_change().mean()

        scores[company] = {
            'SalesGrowth': sales_growth,
            'SalesStability': sales_stability,
            'EPSLevel': eps_level,
            'EPSGrowth': eps_growth
        }

    if not scores:
        return jsonify({"error": "No valid score data"}), 400

    # score_df = pd.DataFrame(scores).T.fillna(0)

    # # 5. Normalize unless only one row
    # if len(score_df) == 1:
    #     norm_df = score_df.copy()
    # else:
    #     scaler = MinMaxScaler()
    #     norm_df = pd.DataFrame(
    #         scaler.fit_transform(score_df),
    #         columns=score_df.columns,
    #         index=score_df.index
    #     )

    # # 6. Final score
    # norm_df['FinalScore'] = (
    #     0.3 * norm_df['SalesGrowth'] +
    #     0.2 * norm_df['SalesStability'] +
    #     0.3 * norm_df['EPSLevel'] +
    #     0.2 * norm_df['EPSGrowth']
    # )
    score_df = pd.DataFrame(scores).T.fillna(0)

    # Always normalize to get proper weight proportions
    scaler = MinMaxScaler()
    normalized = pd.DataFrame(
        scaler.fit_transform(score_df),
        columns=score_df.columns,
        index=score_df.index
    )

    # Compute final score from normalized values
    normalized['FinalScore'] = (
        0.3 * normalized['SalesGrowth'] +
        0.2 * normalized['SalesStability'] +
        0.3 * normalized['EPSLevel'] +
        0.2 * normalized['EPSGrowth']
    )

    # Merge normalized FinalScore into original raw DataFrame
    score_df['FinalScore'] = normalized['FinalScore']


    # 7. Combine with names
    result = []
    for company_id in normalized.index:
        company_rows = sales_df[sales_df['CompanyID'] == company_id]
        company_name_val = company_rows['CompanyName'].iloc[0] if not company_rows.empty else None

        result.append({
            "companyID": company_id,
            "companyName": company_name,
            "finalScore": round(score_df.loc[company_id, 'FinalScore'], 4),
            "salesGrowth": round(score_df.loc[company_id, 'SalesGrowth'], 4),
            "salesStability": round(score_df.loc[company_id, 'SalesStability'], 4),
            "epsLevel": round(score_df.loc[company_id, 'EPSLevel'], 4),
            "epsGrowth": round(score_df.loc[company_id, 'EPSGrowth'], 4),
        })


    # Sort by final score descending
    result = sorted(result, key=lambda x: x['finalScore'], reverse=True)

    return jsonify(result)

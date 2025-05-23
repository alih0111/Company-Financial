from flask import Flask
from flask_cors import CORS
from sales_data import sales_data_bp
from sales_data2 import sales_data2_bp
from run_script import run_script_bp
from run_script2 import run_script2_bp
from sales_data_score import score_bp
from sales_data_score_all import scoreAll_bp
from bulk_fetch import bulk_fetch_bp

app = Flask(__name__)

CORS(app)


app.register_blueprint(sales_data_bp)
app.register_blueprint(sales_data2_bp)
app.register_blueprint(run_script_bp)
app.register_blueprint(run_script2_bp)
app.register_blueprint(score_bp)
app.register_blueprint(scoreAll_bp)
app.register_blueprint(bulk_fetch_bp)

if __name__ == '__main__':
    app.run(port=5000, debug=True)

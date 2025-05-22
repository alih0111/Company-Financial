# from flask import Flask
# from sales_data import sales_data_bp
# from run_script import run_script_bp

# app = Flask(__name__)
# app.register_blueprint(sales_data_bp)
# app.register_blueprint(run_script_bp)

# if __name__ == '__main__':
#     app.run(port=5000, debug=True)



from flask import Flask
from flask_cors import CORS
from sales_data import sales_data_bp
from sales_data2 import sales_data2_bp
from run_script import run_script_bp
from run_script2 import run_script2_bp
from sales_data_score import score_bp

app = Flask(__name__)

# Enable CORS
CORS(app)

# Optionally specify origins like:
# CORS(app, resources={r"/api/*": {"origins": "http://localhost:3000"}})

app.register_blueprint(sales_data_bp)
app.register_blueprint(sales_data2_bp)
app.register_blueprint(run_script_bp)
app.register_blueprint(run_script2_bp)
app.register_blueprint(score_bp)

if __name__ == '__main__':
    app.run(port=5000, debug=True)

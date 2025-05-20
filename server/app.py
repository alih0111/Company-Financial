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
from run_script import run_script_bp

app = Flask(__name__)

# Enable CORS
CORS(app)

# Optionally specify origins like:
# CORS(app, resources={r"/api/*": {"origins": "http://localhost:3000"}})

app.register_blueprint(sales_data_bp)
app.register_blueprint(run_script_bp)

if __name__ == '__main__':
    app.run(port=5000, debug=True)

from flask import Flask, request, jsonify
from datetime import datetime
import os

app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"message": "LibraHell AI Server is running!"})

@app.route("/health")
def health():
    return jsonify({"status": "running", "version": "LibraHell AI v1.0", "time": datetime.utcnow().isoformat()})

@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json(force=True) or {}
        quality = float(data.get("quality", 0))
        confidence = 0.5
        if quality >= 75: confidence += 0.20
        if quality >= 85: confidence += 0.10
        confidence = min(confidence, 1.0)
        return jsonify({
            "approved": confidence >= 0.72,
            "confidence": round(confidence, 4),
            "reason": "LibraHell AI",
            "model": "rule_based_v1",
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({"approved": False, "confidence": 0.0, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

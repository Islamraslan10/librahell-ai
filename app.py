# ============================================================
#  LibraHell AI Server v3.0 - Islam Raslan
#  مع قاعدة بيانات حقيقية من MT5
# ============================================================

from flask import Flask, request, jsonify
from datetime import datetime
import os
import json

app = Flask(__name__)

# ── قاعدة البيانات في الذاكرة ──
trade_data = []
signal_data = []

# ============================================================
#  HEALTH
# ============================================================
@app.route("/")
def index():
    return jsonify({"message": "LibraHell AI Server v3.0 running!"})

@app.route("/health")
def health():
    return jsonify({
        "status":        "running",
        "version":       "LibraHell AI v3.0",
        "trades_stored": len(trade_data),
        "signals_stored": len(signal_data),
        "time":          datetime.utcnow().isoformat()
    })

# ============================================================
#  PREDICT - يستقبل إشارة ويرد بموافقة أو رفض
# ============================================================
@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json(force=True) or {}

        # حفظ الإشارة في قاعدة البيانات
        data["received_at"] = datetime.utcnow().isoformat()
        signal_data.append(data)

        quality     = float(data.get("quality", 0))
        s9_angle    = float(data.get("s9_angle", 90))
        daily_loss  = float(data.get("daily_loss", 0))
        open_trades = float(data.get("open_trades", 0))
        entry       = float(data.get("entry", 0))
        sl          = float(data.get("sl", 0))
        tp          = float(data.get("tp", 0))

        sl_dist  = abs(entry - sl) / entry if entry > 0 else 0
        tp_dist  = abs(tp - entry) / entry if entry > 0 else 0
        rr_ratio = tp_dist / sl_dist if sl_dist > 0 else 1.5

        confidence = 0.55
        reason = []

        if quality >= 80:    confidence += 0.20; reason.append("High quality")
        elif quality >= 70:  confidence += 0.15; reason.append("Good quality")
        elif quality >= 60:  confidence += 0.10; reason.append("OK quality")
        elif quality >= 50:  confidence += 0.05; reason.append("Low quality")
        else:                confidence -= 0.10; reason.append("Very low quality")

        if s9_angle % 360 == 0:   confidence += 0.10; reason.append("360 angle")
        elif s9_angle % 180 == 0: confidence += 0.08; reason.append("180 angle")
        elif s9_angle % 90 == 0:  confidence += 0.05; reason.append("90 angle")

        if rr_ratio >= 2.0:   confidence += 0.08; reason.append("Good RR")
        elif rr_ratio >= 1.5: confidence += 0.05; reason.append("OK RR")

        if daily_loss >= 2.5:  confidence -= 0.20; reason.append("High daily loss")
        if open_trades >= 4:   confidence -= 0.10; reason.append("Many trades open")

        confidence = max(0.0, min(1.0, confidence))

        return jsonify({
            "approved":   confidence >= 0.65,
            "confidence": round(confidence, 4),
            "reason":     " | ".join(reason),
            "model":      "rule_based_v3",
            "timestamp":  datetime.utcnow().isoformat(),
            "symbol":     data.get("symbol", "")
        })

    except Exception as e:
        return jsonify({
            "approved": True, "confidence": 0.60,
            "error": str(e), "reason": "Fallback"
        }), 200

# ============================================================
#  TRADE RESULT - يستقبل نتيجة الصفقة من MT5
# ============================================================
@app.route("/trade_result", methods=["POST"])
def trade_result():
    """
    MT5 يرسل نتيجة كل صفقة هنا بعد إغلاقها
    هذه البيانات ستُستخدم لتدريب الـ AI
    """
    try:
        data = request.get_json(force=True) or {}
        data["received_at"] = datetime.utcnow().isoformat()
        trade_data.append(data)

        print(f"Trade received: {data.get('symbol')} | "
              f"Profit: {data.get('profit')} | "
              f"Quality: {data.get('quality')}")

        return jsonify({
            "status":        "saved",
            "total_trades":  len(trade_data),
            "message":       "Trade data saved for AI training"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================
#  STATS - إحصائيات البيانات المجمّعة
# ============================================================
@app.route("/stats", methods=["GET"])
def stats():
    if not trade_data:
        return jsonify({
            "total_trades":   0,
            "winning_trades": 0,
            "losing_trades":  0,
            "win_rate":       "0%",
            "total_profit":   0,
            "message":        "No trades recorded yet"
        })

    winning = [t for t in trade_data if float(t.get("profit", 0)) > 0]
    losing  = [t for t in trade_data if float(t.get("profit", 0)) <= 0]
    total_profit = sum(float(t.get("profit", 0)) for t in trade_data)
    win_rate = len(winning) / len(trade_data) * 100 if trade_data else 0

    # أفضل الأزواج
    pair_stats = {}
    for t in trade_data:
        sym = t.get("symbol", "Unknown")
        if sym not in pair_stats:
            pair_stats[sym] = {"trades": 0, "profit": 0}
        pair_stats[sym]["trades"] += 1
        pair_stats[sym]["profit"] += float(t.get("profit", 0))

    best_pair = max(pair_stats, key=lambda x: pair_stats[x]["profit"]) if pair_stats else "N/A"

    return jsonify({
        "total_trades":   len(trade_data),
        "winning_trades": len(winning),
        "losing_trades":  len(losing),
        "win_rate":       f"{win_rate:.1f}%",
        "total_profit":   round(total_profit, 2),
        "total_signals":  len(signal_data),
        "best_pair":      best_pair,
        "pair_stats":     pair_stats
    })

# ============================================================
#  DATA - تصدير البيانات كـ JSON للتدريب
# ============================================================
@app.route("/export", methods=["GET"])
def export():
    return jsonify({
        "trades":  trade_data,
        "signals": signal_data,
        "exported_at": datetime.utcnow().isoformat()
    })

# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"LibraHell AI Server v3.0 starting on port {port}")
    app.run(host="0.0.0.0", port=port)

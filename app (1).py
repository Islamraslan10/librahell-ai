# ============================================================
#  LibraHell AI Server v4.0 - Islam Raslan
#  متصل فعليًا بـ Supabase (signals, trade_results, pair_stats)
# ============================================================

from flask import Flask, request, jsonify
from datetime import datetime, timezone
import os
import requests

app = Flask(__name__)

# ── Supabase config (set these as Environment Variables in Railway) ──
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")  # service_role key (bypasses RLS)

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# ── Fallback in-memory cache (kept so /stats still works even if Supabase is briefly down) ──
trade_data = []
signal_data = []


def supabase_insert(table: str, payload: dict):
    """Insert a row into a Supabase table via PostgREST. Returns True/False."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f"[Supabase] Missing SUPABASE_URL / SUPABASE_SERVICE_KEY - skipped insert into {table}")
        return False
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**SB_HEADERS, "Prefer": "return=minimal"},
            json=payload,
            timeout=8,
        )
        if resp.status_code not in (200, 201, 204):
            print(f"[Supabase] Insert into {table} failed: {resp.status_code} | {resp.text[:300]}")
            return False
        return True
    except Exception as e:
        print(f"[Supabase] Insert into {table} error: {e}")
        return False


def supabase_get(table: str, params: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    try:
        resp = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=SB_HEADERS, params=params, timeout=8)
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception as e:
        print(f"[Supabase] GET {table} error: {e}")
        return []


def supabase_upsert(table: str, payload: dict, on_conflict: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={on_conflict}",
            headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=payload,
            timeout=8,
        )
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        print(f"[Supabase] Upsert {table} error: {e}")
        return False


def unix_to_iso(ts):
    try:
        if ts is None or int(ts) == 0:
            return None
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def update_pair_stats(symbol: str, profit: float):
    """Recompute running aggregates for one symbol and upsert into pair_stats."""
    existing = supabase_get("pair_stats", {"symbol": f"eq.{symbol}", "select": "*"})
    row = existing[0] if existing else {
        "symbol": symbol, "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "total_profit": 0, "best_trade": 0, "worst_trade": 0,
    }

    total_trades = int(row.get("total_trades") or 0) + 1
    winning = int(row.get("winning_trades") or 0) + (1 if profit > 0 else 0)
    losing = int(row.get("losing_trades") or 0) + (1 if profit <= 0 else 0)
    total_profit = float(row.get("total_profit") or 0) + profit
    best_trade = max(float(row.get("best_trade") or 0), profit)
    worst_trade = min(float(row.get("worst_trade") or 0), profit)
    win_rate = round((winning / total_trades) * 100, 2) if total_trades else 0
    avg_profit = round(total_profit / total_trades, 2) if total_trades else 0

    supabase_upsert("pair_stats", {
        "symbol": symbol,
        "total_trades": total_trades,
        "winning_trades": winning,
        "losing_trades": losing,
        "win_rate": win_rate,
        "total_profit": round(total_profit, 2),
        "avg_profit": avg_profit,
        "best_trade": round(best_trade, 2),
        "worst_trade": round(worst_trade, 2),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="symbol")


# ============================================================
#  HEALTH
# ============================================================
@app.route("/")
def index():
    return jsonify({"message": "LibraHell AI Server v4.0 running!", "supabase_connected": bool(SUPABASE_URL and SUPABASE_KEY)})

@app.route("/health")
def health():
    return jsonify({
        "status":         "running",
        "version":        "LibraHell AI v4.0",
        "supabase_connected": bool(SUPABASE_URL and SUPABASE_KEY),
        "trades_cached":  len(trade_data),
        "signals_cached": len(signal_data),
        "time":           datetime.now(timezone.utc).isoformat()
    })

# ============================================================
#  PREDICT - يستقبل إشارة ويرد بموافقة أو رفض
# ============================================================
@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json(force=True) or {}
        data["received_at"] = datetime.now(timezone.utc).isoformat()
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
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "symbol":     data.get("symbol", "")
        })

    except Exception as e:
        return jsonify({
            "approved": True, "confidence": 0.60,
            "error": str(e), "reason": "Fallback"
        }), 200

# ============================================================
#  SIGNAL_LOG - يستقبل كل إشارة اتقيّمت (اتنفذت أو اترفضت) ويحفظها
#  في جدول signals بـ Supabase - ده مصدر بيانات تدريب XGBoost
# ============================================================
@app.route("/signal_log", methods=["POST"])
def signal_log():
    try:
        data = request.get_json(force=True) or {}
        data["received_at"] = datetime.now(timezone.utc).isoformat()
        signal_data.append(data)

        signal_num = data.get("signal")
        signal_type = "BUY" if signal_num == 1 else ("SELL" if signal_num == -1 else None)

        s9_level = data.get("s9_level")
        s9_angle = data.get("s9_angle")
        gann_level = f"{s9_angle}°@{s9_level}" if (s9_level is not None and s9_angle is not None) else None

        executed = bool(data.get("executed", False))

        row = {
            "symbol":            data.get("symbol"),
            "magic_number":      data.get("magic_number"),        # None until EA sends it
            "strategy_type":     data.get("strategy_type", "SCALPING"),
            "signal_type":       signal_type,
            "gann_level":        gann_level,
            "entry_price":       data.get("entry"),
            "stop_loss":         data.get("sl"),
            "take_profit":       data.get("tp"),
            "spread_at_signal":  data.get("spread_pts"),
            "news_filter_passed": not bool(data.get("news_active", False)),
            "ai_score":          data.get("ai_score"),             # None until EA sends it
            "executed":          executed,
            "rejection_reason":  None if executed else data.get("outcome"),
            "signal_time":       unix_to_iso(data.get("timestamp")) or datetime.now(timezone.utc).isoformat(),
        }

        ok = supabase_insert("signals", row)

        return jsonify({"status": "saved" if ok else "cached_only", "total_signals": len(signal_data)}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================
#  TRADE RESULT - يستقبل نتيجة الصفقة من MT5 بعد إغلاقها
# ============================================================
@app.route("/trade_result", methods=["POST"])
def trade_result():
    try:
        data = request.get_json(force=True) or {}
        data["received_at"] = datetime.now(timezone.utc).isoformat()
        trade_data.append(data)

        profit = float(data.get("profit", 0))
        symbol = data.get("symbol", "")

        s9_level = data.get("s9_level")
        s9_angle = data.get("s9_angle")
        gann_level = f"{s9_angle}°@{s9_level}" if (s9_level is not None and s9_angle is not None) else None

        row = {
            "ticket":          data.get("ticket"),
            "symbol":          symbol,
            "magic_number":    data.get("magic_number"),      # None until EA sends it
            "strategy_type":   data.get("strategy_type", "SCALPING"),
            "order_type":      data.get("direction"),
            "lot_size":        data.get("volume"),
            "open_price":      data.get("open_price"),        # None until EA sends it
            "close_price":     data.get("price"),
            "stop_loss":       data.get("sl"),                # None until EA sends it
            "take_profit":     data.get("tp"),                # None until EA sends it
            "profit":          profit,
            "profit_pips":     data.get("profit_pips"),       # None until EA sends it
            "risk_percent":    data.get("risk_percent"),      # None until EA sends it
            "open_time":       unix_to_iso(data.get("open_time")),
            "close_time":      unix_to_iso(data.get("close_time")),
            "account_type":    data.get("acc_type"),
            "ai_filtered":     data.get("ai_enabled"),         # None until EA sends it
            "gann_level":      gann_level,
        }

        ok = supabase_insert("trade_results", row)
        if ok and symbol:
            update_pair_stats(symbol, profit)

        print(f"Trade received: {symbol} | Profit: {profit} | Saved: {ok}")

        return jsonify({
            "status":       "saved" if ok else "cached_only",
            "total_trades": len(trade_data),
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================
#  STATS - إحصائيات (من الذاكرة المؤقتة، سريع وبسيط)
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

    pair_stats_local = {}
    for t in trade_data:
        sym = t.get("symbol", "Unknown")
        if sym not in pair_stats_local:
            pair_stats_local[sym] = {"trades": 0, "profit": 0}
        pair_stats_local[sym]["trades"] += 1
        pair_stats_local[sym]["profit"] += float(t.get("profit", 0))

    best_pair = max(pair_stats_local, key=lambda x: pair_stats_local[x]["profit"]) if pair_stats_local else "N/A"

    return jsonify({
        "total_trades":   len(trade_data),
        "winning_trades": len(winning),
        "losing_trades":  len(losing),
        "win_rate":       f"{win_rate:.1f}%",
        "total_profit":   round(total_profit, 2),
        "total_signals":  len(signal_data),
        "best_pair":      best_pair,
        "pair_stats":     pair_stats_local
    })

# ============================================================
#  DATA - تصدير البيانات كـ JSON (من الذاكرة المؤقتة)
# ============================================================
@app.route("/export", methods=["GET"])
def export():
    return jsonify({
        "trades":  trade_data,
        "signals": signal_data,
        "exported_at": datetime.now(timezone.utc).isoformat()
    })

# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"LibraHell AI Server v4.0 starting on port {port}")
    print(f"Supabase connected: {bool(SUPABASE_URL and SUPABASE_KEY)}")
    app.run(host="0.0.0.0", port=port)

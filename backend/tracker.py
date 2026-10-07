#!/usr/bin/env python3
# ============================================================================
#  SGP CSI · TRACKER + AI  (backend of "PYTHON POWER")
# ============================================================================
#  Connects to the ESP32-S3 nodes (count set by NODE_HOSTS below), applies
#  advanced filters, synchronizes with the frontend, and classifies ACTIVITY
#  with a neural network if a model is trained.
#
#    [Nx ESP32] --ws--> tracker.py --ws(8765)--> index.html (Python button)
#
#  Filters / AI:
#    1. Dynamic handshake and bidirectional configuration sync with frontend.
#    2. Per-node autocalibration (learns real baseline noise and peak motion).
#    3. Position: weighted centroid + attraction toward dominant node.
#    4. KALMAN 2D (constant velocity) -> smooth position + velocity.
#    5. Heuristic posture (standing / crouching).
#    6. Optional AI: neural network (MLP) activity classifier.
# ============================================================================

import asyncio
import csv
import json
import math
import os
import time
import argparse
from collections import deque
import numpy as np
import websockets

# ---- Configuration ----
# List of ESP32 node IPs or mDNS hostnames (3, 4, or any number of nodes):
NODE_HOSTS = ["10.239.61.78", "10.239.61.227", "10.239.61.144", "10.239.61.221"]
NODE_PORT  = 81
NUM_NODES  = len(NODE_HOSTS)
WEB_PORT   = 8765
RATE_HZ    = 20
WINDOW     = 20           # samples (~1 s) for the AI statistics

SHARP      = 3.0
PRESENCE   = 0.05         # ne is measured ABOVE the per-node presence threshold (0 = below it)
POST_SENS  = 1.0
MIN_SPAN   = 0.3          # Minimum threshold-to-peak energy span (keeps ne from saturating on small excursions)
# Presence threshold is RELATIVE to the quiet-room baseline (same idea as the firmware's
# sigma > f * <sigma_noise>): the node's sigma(RSSI) fluctuates proportionally to its own
# level, so a fixed absolute margin is either too tight (false presence) or too loose.
REL_THR    = 2.0          # th = baseline * REL_THR (firmware uses f = 2.2); <1.5 gives false presence
                          # on strong links where RSSI is quantized to 1 dB and sigma is spiky
MIN_MARGIN = 0.05         # ...but at least baseline + 0.05 dB (for near-zero baselines)
WARMUP     = 40           # samples (~2 s) per node used only to learn the baseline before reporting

HERE        = os.path.dirname(os.path.abspath(__file__))
DATASET     = os.path.join(HERE, "dataset.csv")
MODEL_PATH  = os.path.join(HERE, "model.joblib")

# ---- Shared state ----
energy    = [0.0] * NUM_NODES
rssi      = [0] * NUM_NODES
last_seen = [0.0] * NUM_NODES
ne_min    = [None] * NUM_NODES   # low envelope (quiet-room baseline) of e
ne_max    = [1e-3] * NUM_NODES   # tracked peak of e
ne_count  = [0] * NUM_NODES      # samples since (re)calibration

room      = {"w": 5.0, "h": 4.0}


def default_node_positions(n, w, h):
    """Generate default coordinates for N nodes in a room of size w x h."""
    if n == 3:
        return np.array([[0.0, 0.0], [w, 0.0], [w / 2.0, h]], dtype=float)
    elif n == 4:
        return np.array([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]], dtype=float)
    elif n <= 2:
        pts = [[0.0, 0.0], [w, h]]
        return np.array(pts[:n], dtype=float)
    else:
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
        cx, cy = w / 2.0, h / 2.0
        rx, ry = w * 0.45, h * 0.45
        return np.array([[cx + rx * np.cos(a), cy + ry * np.sin(a)] for a in angles], dtype=float)


node_pos = default_node_positions(NUM_NODES, room["w"], room["h"])
clients  = set()


def set_hosts(hosts):
    """Re-initialize all per-node state for a new list of node hosts (--hosts)."""
    global NODE_HOSTS, NUM_NODES, energy, rssi, last_seen, ne_min, ne_max, ne_count, node_pos
    NODE_HOSTS = list(hosts)
    NUM_NODES  = len(NODE_HOSTS)
    energy    = [0.0] * NUM_NODES
    rssi      = [0] * NUM_NODES
    last_seen = [0.0] * NUM_NODES
    ne_min    = [None] * NUM_NODES
    ne_max    = [1e-3] * NUM_NODES
    ne_count  = [0] * NUM_NODES
    node_pos  = default_node_positions(NUM_NODES, room["w"], room["h"])


def clamp(v, a, b):
    return a if v < a else b if v > b else v


# ---------------------------------------------------------------------------
class Kalman2D:
    def __init__(self):
        self.x = np.zeros(4)
        self.P = np.eye(4) * 10.0
        self.H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        self.ready = False

    def predict(self, dt):
        F = np.array([[1, 0, dt, 0], [0, 1, 0, dt],
                      [0, 0, 1, 0],  [0, 0, 0, 1]], dtype=float)
        sa = 1.5
        # Independent white-acceleration noise on x and y (state = [x, y, vx, vy]).
        # A single G = [dt²/2, dt²/2, dt, dt] would make x/y accelerations perfectly
        # correlated, so the filter could only "turn" along the (1,1) diagonal.
        q_pp = dt ** 4 / 4
        q_pv = dt ** 3 / 2
        q_vv = dt ** 2
        Q = np.array([[q_pp, 0, q_pv, 0],
                      [0, q_pp, 0, q_pv],
                      [q_pv, 0, q_vv, 0],
                      [0, q_pv, 0, q_vv]], dtype=float) * sa * sa
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def reset(self):
        self.x = np.zeros(4)
        self.P = np.eye(4) * 10.0
        self.ready = False

    def update(self, z, R):
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P


# ---------------------------------------------------------------------------
def apply_config(d):
    global node_pos, room
    try:
        if "room" in d and isinstance(d["room"], dict):
            w = float(d["room"].get("w", room["w"]))
            h = float(d["room"].get("h", room["h"]))
            if not (math.isfinite(w) and math.isfinite(h) and w > 0 and h > 0):
                raise ValueError(f"bad room size {w}x{h}")
            room["w"], room["h"] = w, h
        if "nodes" in d and isinstance(d["nodes"], list) and len(d["nodes"]) > 0:
            client_nodes = d["nodes"]
            new_pos = []
            for i in range(NUM_NODES):
                if i < len(client_nodes):
                    new_pos.append([float(client_nodes[i]["x"]), float(client_nodes[i]["y"])])
                elif i < len(node_pos):
                    new_pos.append(node_pos[i].tolist())
                else:
                    new_pos.append([0.0, 0.0])
            node_pos = np.array(new_pos, dtype=float)
        print(f"[cfg] applied nodes={node_pos.tolist()}  room={room}")
    except Exception as e:
        print("[cfg] error applying config:", e)


def normalize():
    now = time.time()
    ne = [0.0] * NUM_NODES
    for i in range(NUM_NODES):
        # If node has never sent data or went offline (> 2.0s without packets), output 0.0
        if last_seen[i] == 0.0 or (now - last_seen[i]) > 2.0:
            ne[i] = 0.0
            continue

        e = energy[i]
        # The firmware reports e = 0.0 until its RSSI buffer has >= 15 samples.
        # That is "not ready", not a quiet room: learning it as the baseline would make
        # the threshold ~0 for minutes (it only rises slowly) -> false presence.
        if e <= 0.0:
            ne[i] = 0.0
            continue
        # First real sample after connection: initialize baseline from it
        if ne_min[i] is None:
            ne_min[i] = e
            ne_max[i] = e + MIN_SPAN
            ne_count[i] = 0

        # Baseline = low envelope: drops quickly, rises very slowly (so a person who is
        # present can't drag it up and "disappear" within seconds)
        if e < ne_min[i]:
            ne_min[i] += 0.08 * (e - ne_min[i])
        else:
            ne_min[i] += 0.0005 * (e - ne_min[i])   # ~100 s at 20 Hz, same rate as the firmware

        ne_count[i] += 1
        if ne_count[i] <= WARMUP:
            ne[i] = 0.0
            continue

        th = max(ne_min[i] * REL_THR, ne_min[i] + MIN_MARGIN)

        # Peak tracking: rises immediately on motion, decays slowly
        if e > ne_max[i]:
            ne_max[i] = e
        else:
            ne_max[i] += 0.0020 * (e - ne_max[i])
        if ne_max[i] < th + MIN_SPAN:
            ne_max[i] = th + MIN_SPAN

        # 0 = below the presence threshold, 1 = at the learned peak
        ne[i] = clamp((e - th) / (ne_max[i] - th), 0.0, 1.0)
    return ne


def reset_calibration(i):
    ne_min[i] = None
    ne_max[i] = 1e-3
    ne_count[i] = 0


def measure(ne):
    w = [n ** SHARP for n in ne]
    sw = sum(w)
    if sw <= 1e-6:
        return None
    k = min(NUM_NODES, len(node_pos))
    if k == 0:
        return None
    mx = sum(w[i] * node_pos[i, 0] for i in range(k)) / sw
    my = sum(w[i] * node_pos[i, 1] for i in range(k)) / sw
    sumn = sum(ne)
    dom = int(np.argmax(ne))
    if dom < len(node_pos):
        dominance = ne[dom] / sumn if sumn > 1e-6 else 0.0
        pull = clamp((dominance - 0.30) / 0.45, 0.0, 1.0) * 0.6
        mx = mx * (1 - pull) + node_pos[dom, 0] * pull
        my = my * (1 - pull) + node_pos[dom, 1] * pull
    return mx, my


# ---- feature vector for the AI (independent of the geometry) ----
def features(ne, hist):
    arr = np.array(hist) if len(hist) else np.array([ne])
    mean = arr.mean(0)
    std = arr.std(0)
    sumn = float(sum(ne))
    maxn = float(max(ne))
    spread = float(np.std(ne))
    dom = float(np.argmax(ne)) / max(1, NUM_NODES - 1)
    feat = (list(ne) + list(mean) + list(std)
            + [r / 100.0 for r in rssi] + [sumn, maxn, spread, dom])
    return [float(x) for x in feat]


# ---------------------------------------------------------------------------
async def node_task(i):
    url = f"ws://{NODE_HOSTS[i]}:{NODE_PORT}"
    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                print(f"[node {i}] connected to {url}")
                reset_calibration(i)       # the room may have changed while the node was away
                async for msg in ws:
                    try:
                        d = json.loads(msg)
                        energy[i]    = float(d.get("e", 0))
                        rssi[i]      = int(d.get("rssi", 0))
                        last_seen[i] = time.time()
                    except Exception:
                        pass
        except Exception:
            print(f"[node {i}] no connection ({url}), retrying…")
            await asyncio.sleep(2)


async def sim_task():
    """Simulates a person moving around (to test WITHOUT the nodes)."""
    print("[SIM] generating simulated data (no hardware)")
    t0 = time.time()
    while True:
        await asyncio.sleep(1.0 / RATE_HZ)
        t = time.time() - t0
        px = room["w"] * 0.5 + room["w"] * 0.32 * math.sin(t * 0.45)
        py = room["h"] * 0.5 + room["h"] * 0.32 * math.sin(t * 0.63 + 1.2)
        k = min(NUM_NODES, len(node_pos))
        for i in range(k):
            d = math.hypot(node_pos[i, 0] - px, node_pos[i, 1] - py)
            energy[i] = 1.6 / (d * d + 0.4)
            rssi[i] = -45 - int(d * 4)
            last_seen[i] = time.time()


async def web_handler(ws, *args):
    clients.add(ws)
    print("\n" + "=" * 45)
    print("  >>> WEB CONNECTED — PYTHON POWER ACTIVE <<<")
    print("  The browser is receiving filtered data.")
    print("=" * 45 + "\n")

    # Handshake: send current backend configuration immediately
    init_msg = json.dumps({
        "type": "init",
        "room": room,
        "num_nodes": NUM_NODES,
        "nodes": [{"x": round(float(node_pos[i, 0]), 3), "y": round(float(node_pos[i, 1]), 3)} for i in range(len(node_pos))],
        "hosts": NODE_HOSTS,
    })
    try:
        await ws.send(init_msg)
    except Exception:
        pass

    try:
        async for msg in ws:
            try:
                d = json.loads(msg)
                if d.get("type") == "config":
                    apply_config(d)
                    ack_msg = json.dumps({
                        "type": "config_ack",
                        "room": room,
                        "num_nodes": NUM_NODES,
                        "nodes": [{"x": round(float(node_pos[i, 0]), 3), "y": round(float(node_pos[i, 1]), 3)} for i in range(len(node_pos))],
                    })
                    await ws.send(ack_msg)
            except Exception:
                pass
    finally:
        clients.discard(ws)
        print("[web] browser disconnected")


def load_model():
    if not os.path.exists(MODEL_PATH):
        return None, None
    try:
        import joblib
        model = joblib.load(MODEL_PATH)
        classes = list(model.classes_)
        print(f"[AI] model loaded · classes: {classes}")
        return model, classes
    except Exception as e:
        print("[AI] could not load the model:", e)
        return None, None


# words that count as "crouch/down" for the skeleton animation
CROUCH_WORDS = ("crouch", "squat", "sit", "lying", "down", "floor")


async def filter_loop(model, classes):
    kf = Kalman2D()
    last = time.time()
    crouch = 0.0
    peak = 1e-3
    absent = 0
    hist = deque(maxlen=WINDOW)
    while True:
        await asyncio.sleep(1.0 / RATE_HZ)
        now = time.time()
        dt = max(1e-3, now - last)
        last = now

        online = [(now - last_seen[i]) < 2.0 for i in range(NUM_NODES)]
        ne = normalize()
        hist.append(ne)
        maxn = max(ne) if len(ne) else 0.0
        sumn = sum(ne)
        present = maxn > PRESENCE

        # Person gone for > 2 s: forget the old track, so a re-appearance elsewhere
        # starts from the new measurement instead of sliding over from the old spot.
        absent = 0 if present else absent + 1
        if absent > 2 * RATE_HZ and kf.ready:
            kf.reset()

        kf.predict(dt)
        z = measure(ne) if present else None
        if z is not None:
            if not kf.ready:
                kf.x[0], kf.x[1] = z
                kf.ready = True
            R = np.eye(2) * (0.3 + (1.0 - maxn) * 1.5)
            kf.update(np.array(z), R)
        else:
            # Damp velocity when nobody is detected so the position doesn't drift away
            kf.x[2] *= 0.85
            kf.x[3] *= 0.85
            if np.trace(kf.P) > 100.0:
                kf.P *= 0.98

        # Keep the state itself inside the room (not only the reported value)
        kf.x[0] = clamp(float(kf.x[0]), 0.0, room["w"])
        kf.x[1] = clamp(float(kf.x[1]), 0.0, room["h"])
        x, y = float(kf.x[0]), float(kf.x[1])

        # --- AI: activity classification ---
        activity, act_conf = None, 0.0
        if model is not None and present:
            try:
                feat = features(ne, hist)
                probs = model.predict_proba([feat])[0]
                k = int(np.argmax(probs))
                activity = str(classes[k])
                act_conf = float(probs[k])
            except Exception:
                activity = None

        # --- posture: from the model if it exists, otherwise heuristic ---
        if activity is not None:
            tgt = 1.0 if any(w in activity.lower() for w in CROUCH_WORDS) else 0.0
        else:
            peak = max(peak * 0.999, sumn)
            stand = clamp(sumn / (peak + 1e-6), 0.0, 1.0)
            tgt = clamp((1.0 - stand) * POST_SENS, 0.0, 1.0) if present else 0.0
        crouch += 0.1 * (tgt - crouch)

        pkt = {
            "type": "track",
            "t": int(now * 1000),
            "present": bool(present),
            "x": round(x, 3),
            "y": round(y, 3),
            "vx": round(float(kf.x[2]), 3),
            "vy": round(float(kf.x[3]), 3),
            "conf": round(maxn, 3),
            "crouch": round(float(crouch), 3),
            "posture": "CROUCHING" if crouch > 0.5 else "STANDING",
            "activity": activity,
            "act_conf": round(act_conf, 2),
            "nodes": [
                {"id": i, "e": round(energy[i], 3), "ne": round(ne[i], 3),
                 "rssi": rssi[i], "on": online[i]} for i in range(NUM_NODES)
            ],
        }
        if clients:
            data = json.dumps(pkt)
            await asyncio.gather(*[c.send(data) for c in list(clients)],
                                 return_exceptions=True)


# ---------------------------------------------------------------------------
async def serve_main(sim=False):
    model, classes = load_model()
    if model is None:
        print("[AI] no model: heuristic posture. (record and train for AI)")
    print(f"Serving the web at  ws://localhost:{WEB_PORT}")
    print("Open index.html and click  ⚡ PYTHON POWER")
    sources = [sim_task()] if sim else [node_task(i) for i in range(NUM_NODES)]
    async with websockets.serve(web_handler, "0.0.0.0", WEB_PORT):
        await asyncio.gather(*sources, filter_loop(model, classes))


async def record_main(label, seconds):
    tasks = [asyncio.create_task(node_task(i)) for i in range(NUM_NODES)]
    print("Warming up 2 s…")
    await asyncio.sleep(2.0)
    hist = deque(maxlen=WINDOW)
    rows = []
    t0 = time.time()
    print(f"● RECORDING '{label}' for {seconds}s — perform the activity now.")
    while time.time() - t0 < seconds:
        await asyncio.sleep(1.0 / RATE_HZ)
        ne = normalize()
        hist.append(ne)
        rows.append([label] + features(ne, hist))
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if not rows:
        print("Nothing recorded (--seconds must be > 0).")
        return

    new = not os.path.exists(DATASET)
    with open(DATASET, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            n = len(rows[0]) - 1
            w.writerow(["label"] + [f"f{i}" for i in range(n)])
        w.writerows(rows)
    print(f"✓ +{len(rows)} samples of '{label}' saved to {DATASET}")


def do_train():
    try:
        import joblib
        from sklearn.neural_network import MLPClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import make_pipeline
        from sklearn.model_selection import cross_val_score
    except ImportError:
        print("scikit-learn missing. Install:  pip install -r requirements.txt")
        return
    if not os.path.exists(DATASET):
        print("No dataset.csv. Record first with --record <label>.")
        return

    X, y = [], []
    with open(DATASET) as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            if not row:
                continue
            y.append(row[0])
            X.append([float(v) for v in row[1:]])
    X = np.array(X)
    y = np.array(y)
    labels, counts = np.unique(y, return_counts=True)
    print("Samples per class:", dict(zip(labels.tolist(), counts.tolist())))
    if len(labels) < 2:
        print("You need at least 2 different recorded activities.")
        return

    clf = make_pipeline(
        StandardScaler(),
        MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=3000,
                      early_stopping=True, random_state=0))
    try:
        cv = min(5, int(counts.min()))
        if cv >= 2:
            scores = cross_val_score(clf, X, y, cv=cv)
            print(f"Cross-validation accuracy: {scores.mean() * 100:.1f}% (±{scores.std() * 100:.1f})")
    except Exception as e:
        print("(cross-val skipped:", e, ")")
    clf.fit(X, y)
    import joblib
    joblib.dump(clf, MODEL_PATH)
    print(f"✓ Neural network trained and saved to {MODEL_PATH}")
    print("  Start normally (python tracker.py) and the web will show the activity.")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SGP CSI tracker + AI")
    ap.add_argument("--record", metavar="LABEL", help="record samples of an activity")
    ap.add_argument("--seconds", type=int, default=30, help="recording duration")
    ap.add_argument("--train", action="store_true", help="train the neural network with dataset.csv")
    ap.add_argument("--sim", action="store_true", help="simulated data (test without the nodes)")
    ap.add_argument("--hosts", help="comma-separated node IPs/hostnames, e.g. sgpcsi-0.local,sgpcsi-1.local,sgpcsi-2.local")
    args = ap.parse_args()
    if args.hosts:
        set_hosts([h.strip() for h in args.hosts.split(",") if h.strip()])

    print("=== SGP CSI TRACKER + AI ===")
    print(f"Nodes ({NUM_NODES}): {', '.join(NODE_HOSTS)}")
    try:
        if args.train:
            do_train()
        elif args.record:
            asyncio.run(record_main(args.record, args.seconds))
        else:
            asyncio.run(serve_main(sim=args.sim))
    except KeyboardInterrupt:
        print("\n[tracker] stopped")

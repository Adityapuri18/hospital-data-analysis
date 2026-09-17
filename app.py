"""
Hospital Management Dashboard — Python analytics service.

Reads the patient collection that Express writes to MongoDB and turns it into
statistics with pandas. Because it reads the same collection on every request,
admitting or removing a patient immediately changes every figure it returns.

If MongoDB is not running it falls back to a generated CSV so the service
still works for a demo.

    pip install -r requirements.txt
    python app.py          ->  http://localhost:5000
"""
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from flask import Flask, jsonify
from flask_cors import CORS

CSV_FILE = "patients.csv"
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/hospital_dashboard")
TOTAL_BEDS, ICU_BEDS = 412, 48
DEPTS = ["Emergency", "Cardiology", "Orthopaedics",
         "Paediatrics", "General medicine", "Maternity"]
COLUMNS = ["patientId", "name", "age", "gender", "department", "severity",
           "ward", "admittedAt", "dischargedAt", "waitMinutes", "treatmentCost"]

app = Flask(__name__)
CORS(app)

# --------------------------------------------------------------------------
# Where the data comes from
# --------------------------------------------------------------------------
try:
    from pymongo import MongoClient
    _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
    _client.admin.command("ping")
    _collection = _client.get_database().patients
    MONGO_OK = True
    print("Reading patients from MongoDB")
except Exception as exc:                                  # noqa: BLE001
    _collection = None
    MONGO_OK = False
    print(f"MongoDB unavailable ({exc.__class__.__name__}). Using {CSV_FILE} instead.")


def build_csv(n=240):
    """Sample data, used only when MongoDB is not running.
    Severity is deliberately linked to length of stay so the analysis has a
    real relationship to find."""
    rng = np.random.default_rng(42)
    severity = rng.choice(["Stable", "Urgent", "Critical"], n, p=[.62, .28, .10])
    stay = np.clip(rng.gamma(2.0, 1.8, n)
                   + np.where(severity == "Critical", 4.5,
                              np.where(severity == "Urgent", 1.6, 0)), .2, 30).round(1)
    admitted = [datetime.now() - timedelta(minutes=int(m))
                for m in rng.integers(0, 14 * 24 * 60, n)]

    df = pd.DataFrame({
        "patientId": [f"AGH-{i:05d}" for i in range(10000, 10000 + n)],
        "name": [f"Patient {i}" for i in range(1, n + 1)],
        "age": np.clip(rng.normal(41, 19, n), 0, 97).astype(int),
        "gender": rng.choice(["Male", "Female"], n, p=[.51, .49]),
        "department": rng.choice(DEPTS, n, p=[.24, .18, .14, .13, .20, .11]),
        "severity": severity,
        "ward": rng.choice(["A", "B", "C", "ICU"], n, p=[.32, .30, .26, .12]),
        "admittedAt": admitted,
        "waitMinutes": np.clip(rng.normal(26, 11, n), 2, 120).astype(int),
    })
    df["treatmentCost"] = (stay * rng.normal(4200, 900, n)).round(0)
    ends = df.admittedAt + pd.to_timedelta(stay, unit="D")
    df["dischargedAt"] = ends.where(ends < datetime.now())
    df.to_csv(CSV_FILE, index=False)
    print(f"Created {CSV_FILE} with {n} sample records")
    return df


def get_df():
    """Fresh snapshot of the patient record, as a DataFrame."""
    if MONGO_OK:
        docs = list(_collection.find({}, {"_id": 0}))
        df = pd.DataFrame(docs, columns=COLUMNS) if docs else pd.DataFrame(columns=COLUMNS)
    elif os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
    else:
        df = build_csv()

    for col in ("admittedAt", "dischargedAt"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ("age", "waitMinutes", "treatmentCost"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def admitted(df):
    """Patients with no discharge date — the ones inside the hospital."""
    return df[df.dischargedAt.isna()]


def stay_days(df):
    return (df.dischargedAt - df.admittedAt).dt.total_seconds() / 86400


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.route("/api/live")
def live():
    """Headline numbers for the overview page."""
    df = get_df()
    if df.empty:
        return jsonify({"empty": True, "message": "No patient records yet"})

    inside = admitted(df)
    today = pd.Timestamp.now().normalize()
    occupied = min(len(inside), TOTAL_BEDS)
    done = df[df.dischargedAt.notna()]

    return jsonify({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "census": int(occupied),
        "totalRecords": int(len(df)),
        "admittedToday": int((df.admittedAt >= today).sum()),
        "dischargedToday": int((done.dischargedAt >= today).sum()),
        "criticalNow": int((inside.severity == "Critical").sum()),
        "icuInUse": int((inside.ward == "ICU").sum()),
        "icuBeds": ICU_BEDS,
        "beds": {
            "total": TOTAL_BEDS,
            "occupied": int(occupied),
            "available": int(max(TOTAL_BEDS - occupied, 0)),
            "occupancyPct": round(occupied / TOTAL_BEDS * 100, 1),
        },
        "avgWaitMinutes": int(inside.waitMinutes.mean()) if len(inside) else 0,
        "avgStayDays": round(float(stay_days(done).mean()), 1) if len(done) else 0.0,
        "avgAge": int(df.age.mean()),
        "avgCost": int(df.treatmentCost.mean()),
    })


@app.route("/api/departments")
def departments():
    """Active cases, average wait and average cost per department."""
    df = get_df()
    inside = admitted(df)
    if inside.empty:
        return jsonify([])

    g = (inside.groupby("department")
         .agg(activeCases=("patientId", "count"),
              avgWait=("waitMinutes", "mean"),
              avgCost=("treatmentCost", "mean"),
              critical=("severity", lambda s: int((s == "Critical").sum())))
         .round(1).reset_index())

    done = df[df.dischargedAt.notna()].copy()
    if not done.empty:
        done["stay"] = stay_days(done)
        g = g.merge(done.groupby("department").stay.mean().round(1)
                    .rename("avgStayDays").reset_index(), on="department", how="left")
    g = g.fillna(0).sort_values("activeCases", ascending=False)
    return jsonify(g.to_dict(orient="records"))


@app.route("/api/trend")
def trend():
    """Admissions and discharges per hour for the last 12 hours."""
    df = get_df()
    since = pd.Timestamp.now().floor("h") - pd.Timedelta(hours=11)
    idx = pd.date_range(since, periods=12, freq="h")

    adm = (df[df.admittedAt >= since].set_index("admittedAt")
           .resample("h").size().reindex(idx, fill_value=0).rename("admissions"))
    dis = (df[df.dischargedAt >= since].set_index("dischargedAt")
           .resample("h").size().reindex(idx, fill_value=0).rename("discharges"))

    out = pd.concat([adm, dis], axis=1).fillna(0).astype(int)
    return jsonify([{"hour": t.strftime("%H:%M"), **r}
                    for t, r in out.to_dict(orient="index").items()])


@app.route("/api/analysis")
def analysis():
    """Everything the patient-data page charts: severity, age bands, and the
    relationship between severity and how long people stay."""
    df = get_df()
    if df.empty:
        return jsonify({"empty": True})

    inside = admitted(df)
    bands = pd.cut(df.age, bins=[-1, 12, 25, 40, 60, 120],
                   labels=["0-12", "13-25", "26-40", "41-60", "60+"])
    done = df[df.dischargedAt.notna()].copy()
    by_severity_stay = {}
    if not done.empty:
        done["stay"] = stay_days(done)
        by_severity_stay = done.groupby("severity").stay.mean().round(1).to_dict()

    return jsonify({
        "severity": inside.severity.value_counts().to_dict(),
        "ageBands": bands.value_counts().sort_index().to_dict(),
        "gender": df.gender.value_counts().to_dict(),
        "wards": inside.ward.value_counts().to_dict(),
        "avgStayBySeverity": by_severity_stay,
    })


@app.route("/api/patients")
def patients():
    """The 50 most recent records, newest first."""
    df = get_df().sort_values("admittedAt", ascending=False).head(50)
    df = df.where(pd.notna(df), None)
    return jsonify([{
        "patientId": r.patientId, "name": r.name, "age": r.age,
        "gender": r.gender, "department": r.department, "severity": r.severity,
        "ward": r.ward,
        "admittedAt": r.admittedAt.isoformat() if pd.notna(r.admittedAt) else None,
        "dischargedAt": r.dischargedAt.isoformat() if pd.notna(r.dischargedAt) else None,
        "waitMinutes": r.waitMinutes, "treatmentCost": r.treatmentCost,
    } for r in df.itertuples()])


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "source": "mongodb" if MONGO_OK else "csv",
                    "records": int(len(get_df()))})


if __name__ == "__main__":
    print("Analytics service on http://localhost:5000")
    app.run(debug=True, port=5000)

/**
 * Hospital Management Dashboard — Express + MongoDB API.
 *
 * MongoDB holds the patient record. Express exposes it for adding, discharging
 * and removing patients, and forwards every analytics question to the Python
 * service, which reads the same collection with pandas. So a patient you add
 * here changes the analysis there.
 *
 *   npm install
 *   npm run seed      load 240 sample patients
 *   npm start         http://localhost:4000
 *
 * If MongoDB is not running the server still starts and serves the dashboard.
 */
require("dotenv").config();
const express = require("express");
const mongoose = require("mongoose");
const cors = require("cors");
const axios = require("axios");

const PORT = process.env.PORT || 4000;
const MONGO_URI = process.env.MONGO_URI || "mongodb://127.0.0.1:27017/hospital_dashboard";
const PYTHON_API = process.env.PYTHON_API || "http://localhost:5000";

const DEPTS = ["Emergency", "Cardiology", "Orthopaedics",
               "Paediatrics", "General medicine", "Maternity"];
const SEVERITIES = ["Stable", "Urgent", "Critical"];
const WARDS = ["A", "B", "C", "ICU"];

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(__dirname));      // serves dashboard.html at /

/* -------------------------------------------------------------------------
 * Patient model
 * ---------------------------------------------------------------------- */
const patientSchema = new mongoose.Schema(
  {
    patientId:  { type: String, required: true, unique: true },
    name:       { type: String, required: true, trim: true },
    age:        { type: Number, min: 0, max: 120, required: true },
    gender:     { type: String, enum: ["Male", "Female", "Other"], default: "Other" },
    department: { type: String, enum: DEPTS, required: true },
    severity:   { type: String, enum: SEVERITIES, default: "Stable" },
    ward:       { type: String, enum: WARDS, default: "A" },
    bedNumber:  Number,
    admittedAt:   { type: Date, default: Date.now },
    dischargedAt: { type: Date, default: null },
    waitMinutes:   { type: Number, min: 0, default: 0 },
    treatmentCost: { type: Number, min: 0, default: 0 },
  },
  { timestamps: true }
);

patientSchema.index({ dischargedAt: 1, department: 1 });

const Patient = mongoose.model("Patient", patientSchema);

/* -------------------------------------------------------------------------
 * Patient routes — this is what changes the analysis
 * ---------------------------------------------------------------------- */

// List patients:  /api/patients?department=Cardiology&status=in&search=rohan
app.get("/api/patients", async (req, res) => {
  try {
    const { department, severity, status, search, limit = 100 } = req.query;
    const filter = {};
    if (department) filter.department = department;
    if (severity) filter.severity = severity;
    if (status === "in") filter.dischargedAt = null;
    if (status === "out") filter.dischargedAt = { $ne: null };
    if (search) filter.$or = [
      { name: new RegExp(search, "i") },
      { patientId: new RegExp(search, "i") },
    ];

    const patients = await Patient.find(filter).sort({ admittedAt: -1 }).limit(Number(limit));
    res.json(patients);
  } catch (err) {
    res.status(500).json({ error: "Could not load patients", detail: err.message });
  }
});

// Admit a patient. The id is generated here so the form does not need one.
app.post("/api/patients", async (req, res) => {
  try {
    const count = await Patient.countDocuments();
    const patient = await Patient.create({
      patientId: req.body.patientId || `AGH-${10000 + count + 1}`,
      ...req.body,
    });
    res.status(201).json(patient);
  } catch (err) {
    res.status(400).json({ error: "Could not admit patient", detail: err.message });
  }
});

// Discharge: sets the date the analysis uses to measure length of stay.
app.patch("/api/patients/:patientId/discharge", async (req, res) => {
  try {
    const patient = await Patient.findOneAndUpdate(
      { patientId: req.params.patientId },
      { dischargedAt: new Date() },
      { new: true }
    );
    if (!patient) return res.status(404).json({ error: "No patient with that id" });
    res.json(patient);
  } catch (err) {
    res.status(400).json({ error: "Discharge failed", detail: err.message });
  }
});

// Remove the record entirely.
app.delete("/api/patients/:patientId", async (req, res) => {
  try {
    const patient = await Patient.findOneAndDelete({ patientId: req.params.patientId });
    if (!patient) return res.status(404).json({ error: "No patient with that id" });
    res.json({ removed: patient.patientId });
  } catch (err) {
    res.status(400).json({ error: "Delete failed", detail: err.message });
  }
});

// Department stats computed by MongoDB itself, for comparison with pandas.
app.get("/api/patients/stats", async (req, res) => {
  try {
    const stats = await Patient.aggregate([
      { $match: { dischargedAt: null } },
      { $group: {
          _id: "$department",
          activeCases: { $sum: 1 },
          avgWait: { $avg: "$waitMinutes" },
          critical: { $sum: { $cond: [{ $eq: ["$severity", "Critical"] }, 1, 0] } },
      } },
      { $project: { _id: 0, department: "$_id", activeCases: 1, critical: 1,
                    avgWait: { $round: ["$avgWait", 1] } } },
      { $sort: { activeCases: -1 } },
    ]);
    res.json(stats);
  } catch (err) {
    res.status(500).json({ error: "Aggregation failed", detail: err.message });
  }
});

/* -------------------------------------------------------------------------
 * Analytics proxy
 * The browser talks only to Express. Express forwards analytics questions to
 * the Python service, so pandas stays the single place where statistics are
 * computed.
 * ---------------------------------------------------------------------- */
const forward = (path) => async (req, res) => {
  try {
    const { data } = await axios.get(`${PYTHON_API}${path}`, { timeout: 5000 });
    res.json(data);
  } catch {
    res.status(502).json({
      error: "Analytics service is not responding",
      hint: "Start it in this folder with: python app.py",
    });
  }
};

app.get("/api/live", forward("/api/live"));
app.get("/api/analytics/departments", forward("/api/departments"));
app.get("/api/analytics/trend", forward("/api/trend"));
app.get("/api/analytics/analysis", forward("/api/analysis"));

app.get("/api/health", async (req, res) => {
  let analytics = "unreachable";
  try {
    const { data } = await axios.get(`${PYTHON_API}/api/health`, { timeout: 2000 });
    analytics = data;
  } catch { /* leave as unreachable */ }
  res.json({
    status: "ok",
    mongoConnected: mongoose.connection.readyState === 1,
    analytics,
  });
});

/* -------------------------------------------------------------------------
 * Seeding:  npm run seed
 * ---------------------------------------------------------------------- */
const FIRST = ["Rohan", "Aditi", "Imran", "Sneha", "Vikram", "Meera", "Arjun",
               "Kavya", "Priya", "Dev", "Neha", "Omkar"];
const LAST = ["Deshmukh", "Kulkarni", "Shaikh", "Rao", "Iyer", "Bhosale",
              "Naik", "Verma", "Joshi", "Gaikwad"];
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const rnd = (a, b) => Math.floor(Math.random() * (b - a + 1)) + a;

async function seed() {
  await Patient.deleteMany({});

  const docs = Array.from({ length: 240 }, (_, i) => {
    const severity = pick(SEVERITIES);
    // Critical cases stay longer. This is the relationship the analysis finds.
    const stayDays = 1 + Math.random() * 4 +
      (severity === "Critical" ? 4.5 : severity === "Urgent" ? 1.6 : 0);
    const admittedAt = new Date(Date.now() - rnd(0, 14 * 24 * 60) * 60000);
    const ends = new Date(admittedAt.getTime() + stayDays * 864e5);

    return {
      patientId: `AGH-${10000 + i}`,
      name: `${pick(FIRST)} ${pick(LAST)}`,
      age: rnd(1, 92),
      gender: pick(["Male", "Female"]),
      department: pick(DEPTS),
      severity,
      ward: severity === "Critical" && Math.random() < 0.6 ? "ICU" : pick(["A", "B", "C"]),
      bedNumber: rnd(1, 412),
      admittedAt,
      dischargedAt: ends < new Date() ? ends : null,
      waitMinutes: rnd(5, 70),
      treatmentCost: Math.round(stayDays * rnd(3600, 5400)),
    };
  });

  await Patient.insertMany(docs);
  const active = docs.filter((d) => !d.dischargedAt).length;
  console.log(`Seeded ${docs.length} patients (${active} still admitted)`);
}

/* ---------------------------------------------------------------------- */
mongoose
  .connect(MONGO_URI)
  .then(async () => {
    console.log("MongoDB connected");
    if (process.argv.includes("--seed")) {
      await seed();
      process.exit(0);
    }
  })
  .catch((err) => {
    console.warn("MongoDB not available:", err.message);
    console.warn("The dashboard still opens; patient routes will return errors.");
    if (process.argv.includes("--seed")) process.exit(1);
  });

app.listen(PORT, () => console.log(`Dashboard and API on http://localhost:${PORT}`));

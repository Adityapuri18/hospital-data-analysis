# Hospital Management Dashboard

A live operations board for a 412-bed hospital, built for a Data Science
subject activity. Python does the analysis, the MERN stack carries the
application. No login screen.

The whole project is this one folder. There are no subdirectories.

## Two sections, both fully working

**Overview** — patient census, bed occupancy, ICU use, average wait, average
length of stay, hourly admission and discharge flow, department load, and
alerts raised from the current data.

**Patient data and analysis** — admit a patient with a form, discharge them,
remove them, search and filter the record, export it as CSV, and see severity
split, age bands and average stay by department.

The two pages read from the same patient record. Admit a Critical patient in
the ICU and, with no refresh, the census rises by one, the critical count
rises, ICU usage rises, the Cardiology bar grows, the severity doughnut
shifts, and the hourly chart picks up the admission. Discharge them and the
length-of-stay figures absorb the new stay. Remove them and every number
returns to where it was. Nothing on either page is a hardcoded or random
figure.

## The fastest way to see it

Double-click **`dashboard.html`**. It runs in any browser with nothing
installed, starts with 520 sample patients, and keeps your changes in the
browser between visits. This is the safest option for a lab demo.

New patients arrive automatically every six seconds so the board looks alive.
Use **Pause intake** if you want the numbers to hold still while you explain
them.

## Running the full stack

```
bash setup.sh          # macOS or Linux
setup.bat              # Windows, double-click it
```

Then, in this folder:

```
Terminal 1:   python app.py      # analytics service, port 5000
Terminal 2:   npm run seed       # load 240 sample patients into MongoDB
              npm start          # API and dashboard, port 4000
```

Open **http://localhost:4000**. Express serves the dashboard itself, so there
is no third server to start.

MongoDB is optional. Without it the dashboard still opens and the Python
service falls back to a generated CSV; only the Express patient routes return
errors. Check `http://localhost:4000/api/health` to see what is connected.

## Files

| File | What it is |
|---|---|
| `dashboard.html` | The complete dashboard. Open it directly, no build step. |
| `app.py` | Flask analytics service. Reads the patient collection and computes every statistic with pandas. |
| `server.js` | Express server: Mongoose schema, patient CRUD, seeding, the analytics proxy, and static hosting. |
| `requirements.txt`, `package.json` | Dependencies. |
| `.env.example` | Ports and the MongoDB connection string. |
| `setup.sh`, `setup.bat` | One-command install. |
| `patients.csv` | Created automatically if MongoDB is not available. |

## How the pieces fit together

```
  Browser (dashboard.html)
        |
        v
  Express + MongoDB  ──── writes ────>  patients collection
  port 4000                                    |
        |                                    reads
        |  forwards analytics                   |
        +──────────────────────>  Flask + pandas
                                  port 5000
```

MongoDB holds the record. Express adds, discharges and deletes patients. The
Python service reads that same collection on every request and returns the
computed statistics, which Express passes back to the browser. That is why a
change on the patient page shows up in the analysis: there is one record and
one place where the statistics are calculated.

## The analysis behind the numbers

- **Census and occupancy** — a patient is inside the hospital when
  `dischargedAt` is empty. Occupancy is that count over 412 beds.
- **Department load** — `groupby("department")` with a multi-column `agg` for
  active cases, mean wait, mean cost and a critical-case tally.
- **Hourly flow** — `resample("h")` on the admission and discharge timestamps,
  reindexed over the last 12 hours so empty hours show as zero.
- **Age bands** — `pd.cut` into five bands, then `value_counts`.
- **Length of stay** — discharge minus admission, averaged per department and
  per severity.

The sample data deliberately links severity to length of stay, so Critical
patients average around 7 days against roughly 3 for Stable. That is the
finding to point at when you are asked what the data shows.

## API reference

| Endpoint | Returns |
|---|---|
| `GET /api/patients` | Records, filterable by department, severity, status, search |
| `POST /api/patients` | Admit a patient |
| `PATCH /api/patients/:patientId/discharge` | Discharge a patient |
| `DELETE /api/patients/:patientId` | Remove a record |
| `GET /api/patients/stats` | Department stats via a MongoDB aggregation pipeline |
| `GET /api/live` | Census, beds, ICU, waits, averages |
| `GET /api/analytics/departments` | Per-department aggregation from pandas |
| `GET /api/analytics/trend` | Hourly admissions and discharges |
| `GET /api/analytics/analysis` | Severity, age bands, wards, stay by severity |
| `GET /api/health` | What is connected and how many records exist |

## If something does not work

- Numbers look frozen → live intake is paused. Press **Resume intake**.
- Want the original sample data back → **Reset to sample data** on the patient
  page.
- `MongoDB not available` in the console → Mongo is not started. The dashboard
  still works.
- Port already in use → change `PORT` in `.env`.

## Ideas if you want to extend it

Replace polling with Socket.IO, predict discharge risk from severity, age and
department with scikit-learn, or add a date filter to compare two weeks.

# Moonlight Movies · Weekly Sales Dashboard (Flask + pandas)

A self-hosted sales dashboard for a movie-theater concession stand
(Pioneer/Polly drinks, popcorn, snowcones, candy, raffle tickets,
chairs, pop-a-shot, and more). You drag in two CSV files and it turns
them into an interactive web report: weekly overview, KPIs, category
breakdowns, top products, trend charts, and CSV/JSON export — no
database required.

> ⚠️ **Data disclosure:** any numbers shown in the live demo are
> **invented / fictional data**, used only to populate and demo the
> dashboard. They don't represent real sales from any actual business.

**🔗 Live demo:** [https://moonlight-movies-analysis.onrender.com](https://moonlight-movies-analysis.onrender.com)

This is a Tailwind (CDN) + Chart.js template. Nothing is hardcoded in
a JSON file: the two CSVs you upload are saved to disk once, and the
Flask server re-reads and recalculates everything with `pandas` on
every `/api/*` request.

## Run

Just open the link: **[https://moonlight-movies-analysis.onrender.com](https://moonlight-movies-analysis.onrender.com)**

Or run it locally:

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser and drag your two
CSVs into the two dropzones (see **Add your data** below). On every
server start, `uploaded_data/` is wiped, so you always start from a
clean slate and drop in fresh files for that run.

## Add your data

The dashboard doesn't ship with a bundled dataset — you upload it
yourself, straight from the browser:

1. Open the app. Two dropzones are shown: **Global** and
   **Individual products**.
2. Drag in (or pick) your two CSVs:
   - **Global CSV** — one row per week: attendance, total units sold,
     net $ revenue, and the $ breakdown per category (Popcorn Sales,
     Snowcones Sales, Chairs Sale, Pop-A-Shot Sales, Raffle-Tickets
     Sales, Nee-Dohs Sale, Candy Sales, Others, etc).
   - **Individual products CSV** — one row per week: units sold per
     individual flavor/product (Pioneer Black Cherry, Polly Root Beer,
     etc).
3. Each file is validated **before** anything is saved: it must parse
   as a semicolon-separated CSV, contain a `Day` column, and have at
   least one row with a valid date in it. If a file fails validation,
   nothing on disk changes and you get back a plain-English reason
   (e.g. "No 'Day' column found — is this the right file?").
4. On success, `/api/upload` overwrites whichever file(s) you sent
   (`uploaded_data/mlm_global.csv` and/or `uploaded_data/mlm_indi.csv`)
   and reports back how many weeks and categories/products it found —
   a quick sanity check that the right file landed in the right slot.
5. From then on, every chart, KPI, and export reads straight from
   those two files. To update the data, just drag in a new version of
   either CSV — no restart needed, everything recalculates instantly.

### CSV format — the details that matter

Both files are parsed the exact same way, so both must follow these
rules:

- **Separator:** semicolon (`;`), not comma. A comma-separated file
  will fail to parse or come out as one giant column.
- **Encoding:** `latin-1`. This is what lets accented characters and
  symbols from typical spreadsheet exports (Excel/Numbers/Google
  Sheets `.csv` downloads) come through without breaking.
- **`Day` column is mandatory** on both files, formatted `d/m/yy`
  (e.g. `07/09/25`). This is what ties a row in the Global CSV to the
  matching row in the Individual products CSV, and what generates the
  week labels used everywhere in the UI (`Week 3 · Sep 07, 2025`).
- **A row only counts as a real week if `Day` parses as a valid
  date.** Blank rows or stray junk rows some spreadsheet apps leave at
  the end of an export are silently skipped — you don't need to clean
  those out by hand.
- **Decimal separator:** numeric cells may use a comma instead of a
  dot (e.g. `0,00`) and are still parsed correctly as `0.00`. Mixing
  both styles in the same file is fine.
- **Missing cells default to 0**, not an error. A week that didn't
  sell any raffle tickets can just leave that cell blank.
- **New categories are picked up automatically.** Any column in the
  Global CSV that isn't one of the fixed metrics (`Day`, `Attendance`,
  `Total Sales`, `Net Sales`, `Polly's`/`Pioneer` totals, `Popcorn`,
  `Snowcones`, `Temperature`, `Category`) is treated as a dynamic
  sub-category — Chairs, Candy, or whatever new item shows up in a
  future week's export — with **no code changes required**. A units
  column is automatically paired with its matching `<Name> Sale(s)`
  revenue column by name (so `Pop-A-Shot` and `Pop-A-Shot Sales`
  become one category), regardless of casing, hyphens, or apostrophes.
- **`Total Sales` is a unit count** (items sold across all
  categories), **not a dollar amount** — don't compare it directly to
  `Net Sales`, which is the actual $ revenue for the week.
- **`Others` is a subtotal, not a separate category** — it should
  equal the sum of Chairs Sale + Pop-A-Shot Sales + Raffle-Tickets
  Sales + Nee-Dohs Sale + Candy Sales. If you add it together with its
  own components elsewhere, you'll double-count revenue.
- **Individual products CSV** just needs `Day` plus one column per
  product (units sold that week). Any column besides `Day` is treated
  as a product — add or remove product columns freely between
  uploads, nothing needs to be registered anywhere.

## Structure

```
moonlight-movies/
├── app.py
├── uploaded_data/          # created at startup, wiped on every restart
│   ├── mlm_global.csv      # written by the UI once you upload it
│   └── mlm_indi.csv        # written by the UI once you upload it
├── index.html
├── styles.css
├── app.js
├── requirements.txt
├── runtime.txt
├── Procfile
└── render.yaml
```

- `uploaded_data/mlm_global.csv` and `uploaded_data/mlm_indi.csv` are
  managed entirely by the app — you never edit them by hand, you just
  drag new CSVs into the browser. If you need to change the paths the
  server reads from, that's `GLOBAL_CSV` / `INDI_CSV` at the top of
  `app.py`.
- Every route that needs data fails the same clean way (a 404 with a
  plain-English message) if a CSV hasn't been uploaded yet for the
  current server run — there's no silent fallback to stale or fake
  data.

## Private version

This is the public/demo version. The **private version** also
includes a weekly **journal** documenting, week by week, what's behind
each change in revenue: what was tried, which new techniques or
changes were applied (pricing, placement, promotions, weather, etc.),
and how they impacted sales — giving real context behind every number
that isn't included here.

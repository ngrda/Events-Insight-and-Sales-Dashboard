# Moonlight Movies · Weekly Sales Dashboard (Flask + pandas)

A self-hosted sales dashboard for a movie-theater concession stand
(Pioneer/Polly drinks, popcorn, snowcones, candy, raffle tickets,
chairs, pop-a-shot, and more). It reads two CSV files with `pandas`
and turns them into an interactive web report: weekly overview, KPIs,
category breakdowns, top products, trend charts, and CSV/JSON export
— no database required.

> ⚠️ **Data disclosure:** the numbers in `data/mlm_global.csv` and
> `data/mlm_indi.csv` are **invented / fictional data**, used only to
> populate and demo the dashboard. They don't represent real sales
> from any actual business.

**🔗 Live demo:** [https://moonlight-movies-analysis.onrender.com](https://moonlight-movies-analysis.onrender.com)

This is a Tailwind (CDN) + Chart.js template. The data is NOT
hardcoded in a JSON file: the Flask server reads the CSV workbook with
`pandas` every time the page requests it.

## Run

Just open the link: **[https://moonlight-movies-analysis.onrender.com](https://moonlight-movies-analysis.onrender.com)**

Or run it locally:

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

## Add new data

1. Edit `data/mlm_global.csv` and `data/mlm_indi.csv` (they sit in the
   `data/` folder next to `app.py`) and add your rows as usual:
   - **mlm_global.csv** — one row per week: attendance, total sales
     (units), net sales ($), and the $ breakdown per category (Popcorn
     Sales, Snowcones Sales, Chairs Sale, Pop-A-Shot Sales,
     Raffle-Tickets Sales, Nee-Dohs Sale, Candy Sales, Others, etc).
   - **mlm_indi.csv** — one row per week: units sold per individual
     flavor (Pioneer Black Cherry, Polly Root Beer, etc).
2. Save the CSV files (semicolon-separated, `;`).
3. Refresh the page in the browser (F5) — no need to restart the
   server or touch any code. Every time the browser hits `/api/*`,
   Flask reopens the CSVs with pandas and recalculates everything from
   scratch (overview, category breakdown, products, weekly detail,
   trends).

## Structure

```
moonlight-movies/
├── app.py
├── data/
│   ├── mlm_global.csv
│   └── mlm_indi.csv
├── index.html
├── styles.css
├── app.js
├── requirements.txt
├── runtime.txt
├── Procfile
└── render.yaml
```



- `mlm_global.csv` and `mlm_indi.csv` must keep those file names and
  stay in the `data/` folder (next to `app.py`). If you move or rename
  them, edit `GLOBAL_CSV` / `INDI_CSV` at the top of `app.py`.
- A row only counts as a real week if `Day` is a valid `d/m/y` date —
  blank rows or stray junk rows at the end of the CSV are skipped
  automatically.
- Numeric cells that use a comma as the decimal separator (e.g.
  `0,00`) are parsed correctly instead of crashing.
- `Total Sales` is a **unit count** (items sold), not a dollar amount —
  it's the sum of all quantity columns. `Net Sales` is the actual
  **dollar revenue** for the week. Don't compare them directly, they're
  in different units.
- `Others` is itself the sum of Chairs Sale + Pop-A-Shot Sales +
  Raffle-Tickets Sales + Nee-Dohs Sale + Candy Sales — it's a subtotal,
  not a separate category. Summing it together with its own components
  would double-count revenue.

## Private version

This is the public/demo version. The **private version** also
includes a weekly **journal** documenting, week by week, what's behind
each change in revenue: what was tried, which new techniques or
changes were applied (pricing, placement, promotions, weather, etc.),
and how they impacted sales — giving real context behind every number
that isn't included here.

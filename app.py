import os, json
from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd

app = Flask(__name__)
CORS(app)

DATA_FILE = 'data.json'

META_MAP = [
    ('Alicia',    'DUCHA DUCALI',   '',          72),
    ('Ana Paula', 'AQUECEDOR',      '',         150),
    ('Andrea',    'PRIMA',          '',         144),
    ('Andris',    'MOMENT',         'Linha 02',  72),
    ('Andris',    'MOMENT',         'Linha 03',  36),
    ('Andris',    'MOMENT',         'Linha 04',  72),
    ('Caroline',  'LUNA',           '',          72),
    ('Caroline',  'MOMENT 4T',      '',          72),
    ('Eliandra',  'AQUECEDOR',      '',         150),
    ('Iliane',    'AQUECEDOR',      '',         150),
    ('Iliane',    'MOMENT 4T',      '',         150),
    ('Karen',     'DUCHA MOVE',     '',          72),
    ('Karen',     'DUCHA SUBLIME',  '',          72),
    ('Ketlin',    'PRIMA',          '',          72),
    ('Ketlin',    'MOMENT',         'Linha 01',  72),
    ('Marianny',  'DUCHA DUCALI',   '',          72),
    ('Marta',     'AQUECEDOR',      '',         150),
    ('Thalia',    'PRIMA',          '',          72),
    ('Yenire',    'AQUECEDOR',      '',         150),
    ('Yenire',    'MOMENT',         'Linha 01',  72),
    ('Yenire',    'MOMENT',         'Linha 02',  72),
    ('Yenire',    'MOMENT',         'Linha 03',  72),
    ('Yorjelis',  'MOMENT',         'Linha 01',  72),
    ('Yorjelis',  'MOMENT',         'Linha 02',  72),
    ('Yorjelis',  'MOMENT',         'Linha 03',  72),
    ('Yorjelis',  'MOMENT',         'Linha 04',  72),
]

def get_meta(inspetor, produto, linha):
    for (ki, kp, kl, meta) in META_MAP:
        if ki in inspetor and kp in produto:
            if kl == '' or kl in str(linha):
                return meta
    return 72

def get_status(pct):
    if pct >= 0.95: return 'SUPEROU'
    elif pct >= 0.85: return 'ATINGIU'
    else: return 'NAO_ATINGIU'

def process_xlsx(path, filter_date=None):
    import datetime
    df = pd.read_excel(path)
    df['_date'] = pd.to_datetime(df['Data inicial'], dayfirst=True).dt.date
    if filter_date:
        df = df[df['_date'] == datetime.date(*[int(x) for x in filter_date.split('-')])]

    insp = df[df['Item']=='Inspetor Responsável'][['Código da avaliação','Resposta']].rename(columns={'Resposta':'Inspetor'})
    insp['Inspetor'] = insp['Inspetor'].str.strip()
    insp['Inspetor'] = insp['Inspetor'].str.replace(r'^Outro.*','Yenire',regex=True)
    insp['Inspetor'] = insp['Inspetor'].str.replace('Yenire Marquez','Yenire',regex=False)
    insp['Inspetor'] = insp['Inspetor'].str.replace(r'^Andris$','Andris Antonio Rivero Romero',regex=True)
    insp['Inspetor'] = insp['Inspetor'].str.replace('Thalia Steffens','Thalia Steffens',regex=False)

    linha = df[df['Item']=='Linha de Montagem'][['Código da avaliação','Resposta']].rename(columns={'Resposta':'Linha'})
    aprov = df[df['Item']=='Aprovação da Peça'].copy()
    aprov['Produto'] = aprov['Tipo de Unidade'].str.replace(r'\s*-\s*PZO$','',regex=True).str.strip()
    aprov = aprov.merge(insp, on='Código da avaliação', how='left')
    aprov = aprov.merge(linha, on='Código da avaliação', how='left')
    aprov['Linha'] = aprov['Linha'].fillna('')
    aprov['Produto_Linha'] = aprov.apply(lambda r: f"{r['Produto']} — {r['Linha']}" if r['Linha'] else r['Produto'], axis=1)

    by_pl = aprov.groupby(['Inspetor','Produto_Linha','Produto','Linha','Resposta']).size().unstack(fill_value=0).reset_index()
    if 'Sim' not in by_pl.columns: by_pl['Sim'] = 0
    if 'Não' not in by_pl.columns: by_pl['Não'] = 0
    by_pl['Total'] = by_pl['Sim'] + by_pl['Não']
    by_pl['Meta'] = by_pl.apply(lambda r: get_meta(r['Inspetor'],r['Produto'],r['Linha']), axis=1)
    by_pl['Pct'] = (by_pl['Total']/by_pl['Meta']).round(4)
    by_pl['Status'] = by_pl['Pct'].apply(get_status)
    return by_pl

def build_result(days_data):
    # days_data: dict of {label: df}
    result = {"inspetores": [], "totals_by_day": {}, "produtos": [], "days": list(days_data.keys())}
    all_inspetores = sorted(set(sum([list(df['Inspetor'].unique()) for df in days_data.values()], [])))

    for lbl, df in days_data.items():
        summary = df.groupby('Inspetor').agg(Total=('Total','sum'), Meta=('Meta','sum')).reset_index()
        summary['Pct'] = summary['Total'] / summary['Meta']
        t = int(summary['Total'].sum())
        m = int(summary['Meta'].sum())
        result["totals_by_day"][lbl] = {
            "total": t, "meta": m, "pct": round(t/m*100,1),
            "n_superou": int((summary['Pct']>=0.95).sum()),
            "n_atingiu": int(((summary['Pct']>=0.85)&(summary['Pct']<0.95)).sum()),
            "n_nao": int((summary['Pct']<0.85).sum()),
        }

    for insp in all_inspetores:
        obj = {"nome": insp, "dias": {}}
        for lbl, df in days_data.items():
            rows = df[df['Inspetor']==insp]
            if len(rows):
                tot = int(rows['Total'].sum())
                met = int(rows['Meta'].sum())
                pct = round(tot/met*100,1)
                obj["dias"][lbl] = {
                    "total": tot, "meta": met, "pct": pct,
                    "status": get_status(tot/met),
                    "linhas": [{"label": r['Produto_Linha'], "total": int(r['Total']),
                                "meta": int(r['Meta']), "pct": round(float(r['Pct'])*100,1),
                                "status": r['Status']} for _, r in rows.iterrows()]
                }
            else:
                obj["dias"][lbl] = None
        result["inspetores"].append(obj)

    all_prods = sorted(set(sum([list(df['Produto'].unique()) for df in days_data.values()], [])))
    for prod in all_prods:
        obj = {"nome": prod, "dias": {}}
        for lbl, df in days_data.items():
            r = df[df['Produto']==prod]
            obj["dias"][lbl] = int(r['Total'].sum()) if len(r) else None
        result["produtos"].append(obj)

    return result

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return None

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False)

@app.route('/')
def index():
    with open('index.html') as f:
        return f.read()

@app.route('/data')
def get_data():
    data = load_data()
    if not data:
        return jsonify({"error": "Sem dados ainda"}), 404
    return jsonify(data)

@app.route('/upload', methods=['POST'])
def upload():
    API_KEY = os.environ.get('API_KEY', 'zagonel2026')
    if request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if 'file' not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    file = request.files['file']
    date_label = request.form.get('date_label')

    tmp_path = f'/tmp/upload_{file.filename}'
    file.save(tmp_path)

    try:
        # Detect dates in file
        df_raw = pd.read_excel(tmp_path)
        df_raw['_date'] = pd.to_datetime(df_raw['Data inicial'], dayfirst=True).dt.date
        unique_dates = sorted(df_raw['_date'].unique())

        # Load existing data
        existing = load_data() or {"inspetores": [], "totals_by_day": {}, "produtos": [], "days": []}
        existing_days = existing.get("days", [])

        # Process each date in the file
        new_days_data = {}
        for d in unique_dates:
            label = f"{d.day:02d}/{d.month:02d}"
            if date_label and len(unique_dates) == 1:
                label = date_label
            df_day = process_xlsx(tmp_path, f"{d.year}-{d.month:02d}-{d.day:02d}")
            if len(df_day) > 0:
                new_days_data[label] = df_day

        if not new_days_data:
            return jsonify({"error": "Nenhum dado encontrado"}), 400

        # Merge with existing — rebuild only new days
        # We need to rebuild full result with all days
        # For simplicity: store per-day raw summary and rebuild
        stored = load_data() or {"_raw": {}}
        if "_raw" not in stored:
            stored["_raw"] = {}

        for label, df in new_days_data.items():
            stored["_raw"][label] = df.to_dict(orient='records')

        # Rebuild full result from all stored days
        all_dfs = {}
        for label, records in stored["_raw"].items():
            all_dfs[label] = pd.DataFrame(records)

        # Sort by date
        def sort_key(lbl):
            parts = lbl.split('/')
            return (int(parts[1]), int(parts[0]))
        all_dfs = dict(sorted(all_dfs.items(), key=lambda x: sort_key(x[0])))

        result = build_result(all_dfs)
        result["_raw"] = stored["_raw"]
        save_data(result)

        os.remove(tmp_path)
        return jsonify({"success": True, "days": list(all_dfs.keys()), "message": f"Processado: {list(new_days_data.keys())}"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

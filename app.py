import os, json, threading, base64, urllib.request
from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DATA_FILE = 'data.json'
CONFIG_FILE = 'config.json'

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
    return 'NAO_ATINGIU'

def build_result(days_data):
    result = {"inspetores": [], "totals_by_day": {}, "produtos": [], "days": list(days_data.keys())}
    all_inspetores = sorted(set(sum([list(df['Inspetor'].unique()) for df in days_data.values()], [])))
    for lbl, df in days_data.items():
        s = df.groupby('Inspetor').agg(Total=('Total','sum'), Meta=('Meta','sum')).reset_index()
        s['Pct'] = s['Total'] / s['Meta']
        t, m = int(s['Total'].sum()), int(s['Meta'].sum())
        result["totals_by_day"][lbl] = {
            "total": t, "meta": m, "pct": round(t/m*100,1),
            "n_superou": int((s['Pct']>=0.95).sum()),
            "n_atingiu": int(((s['Pct']>=0.85)&(s['Pct']<0.95)).sum()),
            "n_nao": int((s['Pct']<0.85).sum()),
        }
    for insp in all_inspetores:
        obj = {"nome": insp, "dias": {}}
        for lbl, df in days_data.items():
            rows = df[df['Inspetor']==insp]
            if len(rows):
                tot, met = int(rows['Total'].sum()), int(rows['Meta'].sum())
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

# GitHub
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO  = os.environ.get('GITHUB_REPO', 'BrunoPedrolo/zagonel-kpi')

def github_save_file(filename, data_str, commit_msg):
    if not GITHUB_TOKEN:
        return
    try:
        content_b64 = base64.b64encode(data_str.encode()).decode()
        sha = None
        try:
            url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}'
            req = urllib.request.Request(url, headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json'
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                sha = json.loads(r.read())['sha']
        except:
            pass
        payload = {"message": commit_msg, "content": content_b64}
        if sha:
            payload["sha"] = sha
        url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}'
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
            headers={'Authorization': f'token {GITHUB_TOKEN}',
                     'Accept': 'application/vnd.github.v3+json',
                     'Content-Type': 'application/json'}, method='PUT')
        urllib.request.urlopen(req, timeout=15)
        print(f"{filename} backup OK")
    except Exception as e:
        print(f"{filename} backup failed: {e}")

def github_load_raw(filename):
    try:
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/{filename}'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()
    except:
        return None

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    raw = github_load_raw(DATA_FILE)
    if raw:
        data = json.loads(raw)
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, ensure_ascii=False)
        return data
    return None

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False)
    threading.Thread(target=github_save_file, args=(DATA_FILE, json.dumps(data, ensure_ascii=False), 'Auto backup KPI data'), daemon=True).start()

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    raw = github_load_raw(CONFIG_FILE)
    if raw:
        cfg = json.loads(raw)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, ensure_ascii=False)
        return cfg
    return {
        'acessos': {},
        'motivos': ['Falta de material','Manutencao de equipamento','Absenteismo','Treinamento / integracao','Problema no processo','Outro'],
        'threshAtinge': 85,
        'threshSuper': 95,
        'metas': {}
    }

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, ensure_ascii=False)
    # Config saved locally only - no GitHub commit to avoid triggering deploys

# Routes
@app.route('/')
def index():
    with open('index.html') as f:
        return f.read()

@app.route('/data')
def get_data():
    data = load_data()
    if not data:
        return jsonify({"error": "Sem dados ainda"}), 404
    clean = {k: v for k, v in data.items() if k != '_raw'}
    return jsonify(clean)

@app.route('/config', methods=['GET'])
def get_config():
    return jsonify(load_config())

@app.route('/config', methods=['POST'])
def set_config():
    API_KEY = os.environ.get('API_KEY', 'zagonel2026')
    if request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    cfg = request.json
    if not cfg:
        return jsonify({"error": "No data"}), 400
    save_config(cfg)
    return jsonify({"success": True})

@app.route('/restore')
def restore():
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    data = load_data()
    if data:
        days = data.get('days', [])
        return f'''<html><body style="font-family:sans-serif;padding:40px;text-align:center">
            <h2 style="color:#22B04B">Dados restaurados!</h2>
            <p>Dias: {', '.join(days)}</p>
            <a href="/" style="display:inline-block;margin-top:20px;background:#22B04B;color:#fff;padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:600">Ir para o dashboard</a>
        </body></html>'''
    return '<html><body style="padding:40px;text-align:center"><h2>Backup nao encontrado</h2></body></html>', 500

@app.route('/upload-page')
def upload_page():
    return '''<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><title>Upload - Zagonel KPI</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f4f6f4;color:#1a2e1a;font-family:-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{background:#fff;border:1.5px solid #d0e8d0;border-radius:16px;padding:40px;max-width:480px;width:100%;text-align:center;box-shadow:0 4px 20px rgba(34,176,75,.08)}
h1{font-size:20px;font-weight:700;color:#1a2e1a;margin-bottom:6px}
p{font-size:13px;color:#5a8a60;margin-bottom:24px}
input[type=file]{display:none}
.ua{border:2px dashed #d0e8d0;border-radius:10px;padding:32px;cursor:pointer;margin-bottom:16px;transition:all .2s;background:#f9fef9}
.ua:hover,.ua.drag{border-color:#22B04B;background:#f0faf0}
.ul{font-size:14px;color:#5a8a60}.ul span{color:#22B04B;font-weight:600}
button{background:#22B04B;color:#fff;border:none;padding:12px 32px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;width:100%;transition:background .15s}
button:hover{background:#1a8f3a}
button:disabled{background:#d0e8d0;color:#a0c0a0;cursor:not-allowed}
.st{margin-top:16px;font-size:13px;padding:12px;border-radius:8px;display:none;line-height:1.5}
.st.ok{background:#e8f5e9;color:#1a6b3a;border:1px solid #a5d6a7;display:block}
.st.err{background:#fff3e0;color:#e65100;border:1px solid #ffcc80;display:block}
.st.loading{background:#f0faf0;color:#3a6e3a;border:1px solid #d0e8d0;display:block}
.fn{font-size:12px;color:#22B04B;margin-bottom:12px;font-weight:500}
a{display:inline-block;margin-top:16px;font-size:12px;color:#5a8a60;text-decoration:none}
a:hover{color:#22B04B}
.progress{height:4px;background:#e8f5e9;border-radius:2px;overflow:hidden;margin-top:8px;display:none}
.progress-fill{height:100%;background:#22B04B;border-radius:2px;width:0%;transition:width .3s}
</style></head>
<body><div class="box">
<h1>Upload de Dados</h1>
<p>Faz upload do arquivo .xlsx exportado do sistema</p>
<div class="ua" id="da" onclick="document.getElementById('fi').click()">
  <input type="file" id="fi" accept=".xlsx" onchange="hf(this.files[0])">
  <div class="ul">Clica ou arrasta o arquivo <span>.xlsx</span> aqui</div>
</div>
<div class="fn" id="fn"></div>
<button id="btn" onclick="go()" disabled>Enviar e atualizar dashboard</button>
<div class="progress" id="prog"><div class="progress-fill" id="prog-fill"></div></div>
<div class="st" id="st"></div>
<a href="/">Ver dashboard</a>
</div>
<script>
let f=null;
const da=document.getElementById('da');
da.addEventListener('dragover',e=>{e.preventDefault();da.classList.add('drag')});
da.addEventListener('dragleave',()=>da.classList.remove('drag'));
da.addEventListener('drop',e=>{e.preventDefault();da.classList.remove('drag');hf(e.dataTransfer.files[0])});
function hf(x){
  if(!x||!x.name.endsWith('.xlsx')){ss('Apenas arquivos .xlsx sao aceitos.','err');return;}
  f=x;
  document.getElementById('fn').textContent='Arquivo: '+x.name+' ('+Math.round(x.size/1024)+'KB)';
  document.getElementById('btn').disabled=false;
}
function ss(m,t){const s=document.getElementById('st');s.innerHTML=m;s.className='st '+t;}
function setProgress(p){document.getElementById('prog').style.display='block';document.getElementById('prog-fill').style.width=p+'%';}
async function go(){
  if(!f)return;
  document.getElementById('btn').disabled=true;
  setProgress(10);
  ss('Acordando servidor...','loading');
  for(let i=0;i<5;i++){
    try{const w=await fetch('/data',{signal:AbortSignal.timeout(8000)});if(w.status!==403)break;}catch(e){}
    await new Promise(r=>setTimeout(r,3000));
    setProgress(10+i*8);
  }
  setProgress(50);
  ss('Processando arquivo... aguarda ate 2 minutos.','loading');
  const fd=new FormData();fd.append('file',f);
  try{
    const r=await fetch('/upload',{method:'POST',headers:{'X-API-Key':'zagonel2026'},body:fd,signal:AbortSignal.timeout(240000)});
    setProgress(90);
    const txt=await r.text();let d;
    try{d=JSON.parse(txt);}catch(e){ss('Servidor ainda processando. Tenta novamente em 30 segundos.','err');document.getElementById('btn').disabled=false;return;}
    if(d.success){
      setProgress(100);
      ss('Dashboard atualizado! Dias: '+d.days.join(', '),'ok');
      if(d.data) sessionStorage.setItem('freshData',JSON.stringify(d.data));
      setTimeout(()=>window.location.href='/',2500);
    }else{
      ss('Erro: '+d.error,'err');
      document.getElementById('btn').disabled=false;
    }
  }catch(e){
    ss('Erro de conexao. Tenta novamente.','err');
    document.getElementById('btn').disabled=false;
  }
}
</script></div></body></html>'''

@app.route('/upload', methods=['POST'])
def upload():
    API_KEY = os.environ.get('API_KEY', 'zagonel2026')
    if request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    if 'file' not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400
    file = request.files['file']
    tmp_path = f'/tmp/upload_{file.filename}'
    file.save(tmp_path)
    try:
        df_raw = pd.read_excel(tmp_path)
        df_raw['_date'] = pd.to_datetime(df_raw['Data inicial'], dayfirst=True).dt.date
        unique_dates = sorted(df_raw['_date'].unique())
        new_days_data = {}
        for d in unique_dates:
            label = f"{d.day:02d}/{d.month:02d}"
            df_day = df_raw[df_raw['_date'] == d].copy()
            insp = df_day[df_day['Item']=='Inspetor Responsável'][['Código da avaliação','Resposta']].rename(columns={'Resposta':'Inspetor'})
            insp['Inspetor'] = insp['Inspetor'].str.strip()
            insp['Inspetor'] = insp['Inspetor'].str.replace(r'^Outro.*','Yenire',regex=True)
            insp['Inspetor'] = insp['Inspetor'].str.replace('Yenire Marquez','Yenire',regex=False)
            insp['Inspetor'] = insp['Inspetor'].str.replace(r'^Andris$','Andris Antonio Rivero Romero',regex=True)
            linha = df_day[df_day['Item']=='Linha de Montagem'][['Código da avaliação','Resposta']].rename(columns={'Resposta':'Linha'})
            aprov = df_day[df_day['Item']=='Aprovação da Peça'].copy()
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
            if len(by_pl) > 0:
                new_days_data[label] = by_pl
        if not new_days_data:
            return jsonify({"error": "Nenhum dado encontrado"}), 400
        stored = load_data() or {"_raw": {}}
        if "_raw" not in stored:
            stored["_raw"] = {}
        for label, df in new_days_data.items():
            stored["_raw"][label] = df.to_dict(orient='records')
        def sort_key(lbl):
            p = lbl.split('/')
            return (int(p[1]), int(p[0]))
        all_dfs = {lbl: pd.DataFrame(recs) for lbl, recs in stored["_raw"].items()}
        all_dfs = dict(sorted(all_dfs.items(), key=lambda x: sort_key(x[0])))
        result = build_result(all_dfs)
        result["_raw"] = stored["_raw"]
        save_data(result)
        try:
            os.remove(tmp_path)
        except:
            pass
        clean = {k: v for k, v in result.items() if k != '_raw'}
        return jsonify({"success": True, "days": list(all_dfs.keys()), "data": clean})
    except Exception as e:
        try:
            os.remove(tmp_path)
        except:
            pass
        return jsonify({"error": str(e)}), 500

# Auto-restore on startup
def startup_restore():
    if not os.path.exists(DATA_FILE):
        print("Restoring data from GitHub...")
        raw = github_load_raw(DATA_FILE)
        if raw:
            with open(DATA_FILE, 'w') as f:
                f.write(raw)
            print("Data restored OK")
    if not os.path.exists(CONFIG_FILE):
        print("Restoring config from GitHub...")
        raw = github_load_raw(CONFIG_FILE)
        if raw:
            with open(CONFIG_FILE, 'w') as f:
                f.write(raw)
            print("Config restored OK")

startup_restore()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

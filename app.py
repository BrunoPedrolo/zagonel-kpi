from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import pandas as pd
import json
import base64
import requests
from datetime import datetime
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

DASHBOARD_URL = 'https://brunopedrolo.github.io/kpi-qualidade-iluminacao/'
GITHUB_TOKEN  = os.environ.get('GITHUB_TOKEN', '')
GITHUB_USER   = 'BrunoPedrolo'
GITHUB_REPO   = 'kpi-qualidade-iluminacao'
GITHUB_BRANCH = 'main'
META_DEFAULT  = 21

CONFIG_DEFAULT = {
    "metas": {},
    "parametros": {
        "threshold_atingiu": 85,
        "threshold_superou": 100
    },
    "motivos": [
        "Falta de material",
        "Manutenção de equipamento",
        "Absenteísmo",
        "Treinamento / integração",
        "Problema no processo",
        "Outro"
    ],
    "colaboradores": {},
    "justificativas": [],
    "senha_admin": "Zagonel@2026",
    "ultima_atualizacao": ""
}

def gh_get(filename):
    url = f'https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}'
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        content = base64.b64decode(data['content']).decode('utf-8')
        return json.loads(content), data['sha']
    return None, None

def gh_put(filename, data, sha=None, msg=None):
    url = f'https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}'
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    content = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    ).decode('utf-8')
    payload = {
        'message': msg or f'Update {filename} - {datetime.now().strftime("%d/%m/%Y %H:%M")}',
        'content': content,
        'branch': GITHUB_BRANCH
    }
    if sha:
        payload['sha'] = sha
    r = requests.put(url, headers=headers, json=payload)
    return r.status_code in [200, 201]

def get_dados():
    data, sha = gh_get('dados.json')
    if data is None:
        data = {'dias': {}, 'ultima_atualizacao': ''}
    return data, sha

def get_config():
    data, sha = gh_get('config.json')
    if data is None:
        data = CONFIG_DEFAULT.copy()
    return data, sha

def processar_xlsx(file):
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip()

    # Itens de aprovação aceitos (múltiplos formatos)
    ITENS_APROV = [
        'Aprovação geral da etapa inspecionada.',
        'Aprovação da Inspeção',
        'A inspeção foi aprovada?',
        'Aprovação da Peça',
    ]
    # Respostas que indicam aprovação
    RESPOSTAS_APROV = ['sim', 'atingiu', 'aprovado', 'aprovada', 'yes']
    # Respostas que indicam reprovação
    RESPOSTAS_REP   = ['não', 'nao', 'reprovado', 'reprovada', 'no', 'não atingiu']

    # Filtrar registros de aprovação (qualquer um dos itens aceitos)
    mask = df['Item'].astype(str).str.strip().isin(ITENS_APROV)
    aprovacao = df[mask].copy()
    if len(aprovacao) == 0:
        return {}

    aprovacao['Data inicial'] = pd.to_datetime(aprovacao['Data inicial'], dayfirst=True, errors='coerce')
    aprovacao['Data'] = aprovacao['Data inicial'].dt.strftime('%d/%m')

    # Resultado: rep se resposta for negativa, apr se positiva
    def classifica(resp):
        r = str(resp).strip().lower()
        if r in RESPOSTAS_REP:   return 'rep'
        if r in RESPOSTAS_APROV: return 'apr'
        return 'apr'  # padrão: aprovar

    aprovacao['resultado'] = aprovacao['Resposta'].apply(classifica)

    # Itens de executor aceitos (múltiplos formatos)
    ITENS_EXEC = ['Executor', 'Executor da Inspeção', 'Inspetor Responsável']
    exec_mask = df['Item'].astype(str).str.strip().isin(ITENS_EXEC)
    executores = df[exec_mask][['Código da avaliação', 'Resposta']].copy()
    executores.columns = ['Código da avaliação', 'Inspetor']
    # Remover duplicatas mantendo o primeiro executor por avaliação
    executores = executores.drop_duplicates(subset=['Código da avaliação'])
    base = aprovacao.merge(executores, on='Código da avaliação', how='left')

    # Tipo de Unidade — buscar direto do df original por código de avaliação
    if 'Tipo de Unidade' in df.columns:
        tipo_map = df.drop_duplicates(subset=['Código da avaliação'])                     .set_index('Código da avaliação')['Tipo de Unidade']                     .to_dict()
        base['Tipo de Unidade'] = base['Código da avaliação'].map(tipo_map).fillna('')
    else:
        base['Tipo de Unidade'] = ''

    resultado = {}
    for (inspetor, data), grupo in base.groupby(['Inspetor', 'Data']):
        if pd.isna(inspetor):
            continue
        total = len(grupo)
        apr   = int((grupo['resultado'] == 'apr').sum())
        rep   = int((grupo['resultado'] == 'rep').sum())
        try:
            pot = int((grupo['Tipo de Unidade'] == 'Iluminação Potência').sum())
            tub = int((grupo['Tipo de Unidade'] == 'Iluminação Tubular').sum())
        except Exception:
            pot = 0
            tub = 0
        pct = round(total / META_DEFAULT * 100, 1)

        if data not in resultado:
            resultado[data] = {}
        resultado[data][inspetor] = {
            't': total, 'apr': apr, 'rep': rep,
            'pot': pot, 'tub': tub, 'pct': pct
        }
    return resultado

# ─── ROTAS ───────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def index():
    return redirect(DASHBOARD_URL)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})

@app.route('/dados', methods=['GET'])
def route_dados():
    dados, _ = get_dados()
    return jsonify(dados)

@app.route('/config', methods=['GET'])
def route_config():
    config, _ = get_config()
    # Nunca expor a senha admin na API pública
    safe = {k: v for k, v in config.items() if k != 'senha_admin'}
    return jsonify(safe)

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
    file = request.files['file']
    if not file.filename.endswith('.xlsx'):
        return jsonify({'erro': 'Apenas arquivos .xlsx são aceitos'}), 400
    try:
        novos = processar_xlsx(file)
        dados, sha = get_dados()
        if 'dias' not in dados:
            dados['dias'] = {}
        for data, inspetores in novos.items():
            if data not in dados['dias']:
                dados['dias'][data] = {}
            for insp, vals in inspetores.items():
                dados['dias'][data][insp] = vals
        dados['ultima_atualizacao'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        ok = gh_put('dados.json', dados, sha)
        if not ok:
            return jsonify({'erro': 'Erro ao salvar no GitHub'}), 500
        dias_processados = list(novos.keys())
        total_insp = sum(v['t'] for d in novos.values() for v in d.values())
        return jsonify({
            'sucesso': True,
            'dias_processados': dias_processados,
            'total_inspecoes': total_insp,
            'mensagem': f'{len(dias_processados)} dia(s) processado(s) com {total_insp} inspeções'
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/config/salvar', methods=['POST'])
def salvar_config():
    """Salva qualquer parte do config. Requer senha admin no header."""
    senha = request.headers.get('X-Admin-Password', '')
    config, sha = get_config()
    if senha != config.get('senha_admin', 'Zagonel@2026'):
        return jsonify({'erro': 'Senha incorreta'}), 401

    body = request.json or {}
    secao = body.get('secao')  # metas, parametros, motivos, colaboradores, justificativas

    if secao == 'metas':
        config['metas'] = body.get('dados', {})
    elif secao == 'parametros':
        config['parametros'] = body.get('dados', {})
    elif secao == 'motivos':
        config['motivos'] = body.get('dados', [])
    elif secao == 'colaboradores':
        config['colaboradores'] = body.get('dados', {})
    elif secao == 'justificativas':
        # Adiciona uma justificativa nova
        nova = body.get('dados', {})
        nova['timestamp'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        if 'justificativas' not in config:
            config['justificativas'] = []
        config['justificativas'].append(nova)
    elif secao == 'senha_admin':
        nova_senha = body.get('dados', {}).get('nova_senha', '')
        if nova_senha:
            config['senha_admin'] = nova_senha
    else:
        return jsonify({'erro': 'Seção inválida'}), 400

    config['ultima_atualizacao'] = datetime.now().strftime('%d/%m/%Y %H:%M')
    ok = gh_put('config.json', config, sha, f'Config update [{secao}]')
    if not ok:
        return jsonify({'erro': 'Erro ao salvar no GitHub'}), 500
    return jsonify({'sucesso': True, 'secao': secao})

@app.route('/justificativa', methods=['POST'])
def registrar_justificativa():
    """Inspetor registra justificativa com sua senha individual."""
    body = request.json or {}
    inspetor = body.get('inspetor', '')
    senha    = body.get('senha', '')
    data     = body.get('data', '')
    motivo   = body.get('motivo', '')
    obs      = body.get('observacao', '')

    config, sha = get_config()
    senhas = config.get('colaboradores', {})

    if inspetor not in senhas or senhas[inspetor] != senha:
        return jsonify({'erro': 'Senha incorreta para este inspetor'}), 401

    nova = {
        'inspetor': inspetor,
        'data': data,
        'motivo': motivo,
        'observacao': obs,
        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M')
    }
    if 'justificativas' not in config:
        config['justificativas'] = []
    config['justificativas'].append(nova)
    config['ultima_atualizacao'] = datetime.now().strftime('%d/%m/%Y %H:%M')

    ok = gh_put('config.json', config, sha, f'Justificativa {inspetor} {data}')
    if not ok:
        return jsonify({'erro': 'Erro ao salvar no GitHub'}), 500
    return jsonify({'sucesso': True})

@app.route('/admin/verificar', methods=['POST'])
def verificar_admin():
    """Verifica senha do admin."""
    body = request.json or {}
    senha = body.get('senha', '')
    config, _ = get_config()
    if senha == config.get('senha_admin', 'Zagonel@2026'):
        return jsonify({'sucesso': True})
    return jsonify({'erro': 'Senha incorreta'}), 401

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)

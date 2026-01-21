from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import io

def motor_baremacion_itacyl(row):
    """
    MOTOR DE BAREMACIÓN AGRONÓMICA - Versión 1.4.5
    AJUSTE QUIRÚRGICO: Tecnoplus Calcio y Rhizovit/Excelis
    """
    # 0. LIMPIEZA DE DATOS (Aseguramos tipado numérico)
    def to_f(v):
        if pd.isna(v) or v is None: return 0.0
        try: return float(str(v).replace(',', '.').strip())
        except: return 0.0

    n = to_f(row.get('n'))
    p2o5 = to_f(row.get('p2o5'))
    k2o = to_f(row.get('k2o'))
    n_nit = to_f(row.get('nitricN'))
    n_amo = to_f(row.get('ammoniacalN'))
    mo = to_f(row.get('organicMatter'))
    s_val = to_f(row.get('s'))
    siex = to_f(row.get('materialSiexId'))
    
    nombre_raw = str(row.get('name', '')).strip()
    nombre = nombre_raw.upper()
    nombre_protegido = f"'{nombre_raw}"

    # 1. CÁLCULO IS (Índice Salinidad)
    is_v = 0
    if any(kw in nombre for kw in ["NITRATO POTASICO", "NIPO", "TECNOPLUS"]):
        is_v = 74
    elif ("NITRATO AMONICO" in nombre or "NAC" in nombre) and n > 25:
        is_v = 104
    else:
        is_v = int(round((n * 1.65) + (p2o5 * 0.5) + (k2o * 1.9)))
        is_v = min(max(is_v, 5), 140)

    # 2. TIPO
    es_cob = row.get('topDressing') is True
    is_liq = row.get('aggregateState') == 'L' or "SOLUB" in nombre
    tipo = "[C,R]" if (es_cob and is_liq) else ("[C]" if es_cob else ("[R]" if is_liq else "[F]"))

    # 3. BAREMO
    # Lista de tecnologías (Actualizada con RHIZOVIT y EXCELIS)
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "NOVATEC", "ENTEC", "NEXUR", "RHIZOVIT", "EXCELIS"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    siex_e_ids = [1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 19, 20, 21, 22]
    es_enm = (not pd.isna(row.get('yearPercent1'))) or (siex in siex_e_ids)

    # PRODUCTOS DE EXCELENCIA: Nota directa de 10,0
    if es_enm or es_tec or any(k in nombre for k in kw_inh):
        return nombre_protegido, tipo, "Bajo", is_v, "10,0"

    # Caso especial: Nitratos de Calcio en cobertera (Actualizado con TECNOPLUS CALCIO)
    if tipo == "[C,R]" and any(k in nombre for k in ["NITRATO DE CALCIO", "SOLUTECK", "CALCINIT", "TECNOPLUS CALCIO"]):
        return nombre_protegido, tipo, "Medio", is_v, "9,5"

    # Lógica acumulativa (Base 6.0)
    puntos = 6.0
    if mo > 20: puntos += 3.0
    if s_val > 2 or n_amo > 10: puntos += 2.0
    
    has_mic = any(to_f(row.get(m)) > 0 for m in ['fe','zn','mn','cu','b','mo','mg'])
    if not has_mic and any(km in nombre for km in ["QUELAT", "MICROS", "MG"]):
        has_mic = True
    if has_mic: puntos += 1.5

    # Bonus P y K > 7
    if p2o5 > 7: puntos += 1.0
    if k2o > 7: puntos += 1.0

    # 4. PENALIZACIONES
    val_n_final = n if not es_cob else n_nit
    riesgo = "Bajo"
    if 10 <= val_n_final <= 20: 
        puntos -= 1.5
        riesgo = "Medio"
    elif val_n_final > 20: 
        puntos -= 3.0
        riesgo = "Alto"

    if is_v < 20: puntos += 1.5
    elif 20 <= is_v < 40: puntos += 0.5
    elif 60 < is_v <= 80: puntos -= 0.5
    elif 80 < is_v <= 100: puntos -= 1.5
    elif is_v > 100: puntos -= 3.0

    final = round(min(max(puntos, 1.0), 10.0), 1)
    return nombre_protegido, tipo, riesgo, is_v, str(final).replace('.', ',')

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            raw_json = json.loads(post_data)
            items = raw_json['items'] if isinstance(raw_json, dict) and 'items' in raw_json else raw_json
            df = pd.DataFrame(items)
            res_df = df.apply(lambda r: pd.Series(motor_baremacion_itacyl(r.to_dict())), axis=1)
            res_df.columns = ['name', 'Tipo', 'Riesgo', 'IS_valor', 'Baremo']
            output = io.BytesIO()
            res_df.to_csv(output, index=False, sep=';', decimal=',', encoding='utf-8-sig')
            self.send_response(200)
            self.send_header('Content-type', 'text/csv; charset=utf-8-sig')
            self.send_header('Content-Disposition', 'attachment; filename="baremo.csv"')
            self.end_headers()
            self.wfile.write(output.getvalue())
        except Exception as e:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"ERROR: {str(e)}".encode('utf-8'))

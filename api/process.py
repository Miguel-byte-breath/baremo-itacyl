from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import io

def motor_baremacion_itacyl(row):
    """
    MOTOR DE BAREMACIÓN AGRONÓMICA - ESCENARIO A
    Versión 1.4.0 | Bonus P/K > 7 | Fix Independencia de Fila
    """
    # 0. LIMPIEZA DE DATOS (Tipado numérico estricto)
    def to_float(val):
        if pd.isna(val) or val is None: return 0.0
        try:
            s_val = str(val).replace(',', '.').strip()
            return float(s_val)
        except: return 0.0

    # Variables analíticas aisladas
    n = to_float(row.get('n'))
    p = to_float(row.get('p2o5'))
    k = to_float(row.get('k2o'))
    n_nit = to_float(row.get('nitricN'))
    n_amo = to_float(row.get('ammoniacalN'))
    mo = to_float(row.get('organicMatter'))
    s_val = to_float(row.get('s'))
    siex = to_float(row.get('materialSiexId'))
    
    nombre_raw = str(row.get('name', '')).strip()
    nombre = nombre_raw.upper()
    nombre_protegido = f"'{nombre_raw}"

    # 1. CÁLCULO DEL ÍNDICE DE SALINIDAD (IS_v)
    IS_v = 0
    
    # Prioridad A: Identificación por nombre
    if any(kw in nombre for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]):
        IS_v = 15
    elif any(kw in nombre for kw in ["NITRATO POTASICO", "NIPO", "TECNOPLUS"]):
        IS_v = 74
    
    # Prioridad B: Nitrato Amónico puro (Solo si N es alto para no atrapar PKs)
    elif ("NITRATO AMONICO" in nombre or "NAC" in nombre) and n > 25:
        IS_v = 104

    # Prioridad C: Fórmula de Rader (Para el resto de productos)
    if IS_v == 0:
        calc_rader = (n * 1.65) + (p * 0.5) + (k * 1.9)
        IS_v = int(round(min(max(calc_rader, 5), 140)))

    # 2. CLASIFICACIÓN TÉCNICA
    siex_e_ids = [1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 19, 20, 21, 22]
    has_min = row.get('yearPercent1') is not None and not pd.isna(row.get('yearPercent1'))
    es_enm = has_min or (siex in siex_e_ids)
    es_cob = row.get('topDressing') is True
    is_liq = row.get('aggregateState') == 'L' or "SOLUB" in nombre
    
    if es_enm: tipo = "[E]"
    elif es_cob: tipo = "[C,R]" if is_liq else "[C]"
    else: tipo = "[R]" if is_liq else "[F]"

    # 3. BAREMO (Puntuación máxima para Tecnologías o Enmiendas)
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    
    if es_enm or es_tec or any(kw in nombre for kw in kw_inh):
        return nombre_protegido, tipo, "Bajo", IS_v, "10,0"

    # Lógica acumulativa (Base 6.0)
    puntos = 6.0
    if mo > 20: puntos += 3.0
    if s_val > 2 or n_amo > 10: puntos += 2.0
    
    # Bonus Micros
    has_mic = any(to_float(row.get(m)) > 0 for m in ['fe','zn','mn','cu','b','mo','mg'])
    if not has_mic and any(kw in nombre for kw in ["QUELAT", "MICROS", "MG"]):
        has_mic = True
    if has_mic: puntos += 1.5

    # NUEVOS UMBRALES DE P y K > 7 (Rebajado de 15)
    if p > 7: puntos += 1.0
    if k > 7: puntos += 1.0

    # 4. PENALIZACIONES (ZVN y Salinidad)
    # Riesgo Nitratos (Mantenemos penalización estricta)
    val_n_final = n if (not es_cob and not es_enm) else n_nit
    riesgo = "Bajo"
    if 10 <= val_n_final <= 20: 
        puntos -= 1.5
        riesgo = "Medio"
    elif val_n_final > 20: 
        puntos -= 3.0
        riesgo = "Alto"

    # Penalización por Salinidad
    if IS_v < 20: puntos += 1.5
    elif 20 <= IS_v < 40: puntos += 0.5
    elif 60 < IS_v <= 80: puntos -= 0.5
    elif 80 < IS_v <= 100: puntos -= 1.5
    elif IS_v > 100: puntos -= 3.0

    final = round(min(max(puntos, 1.0), 10.0), 1)
    return nombre_protegido, tipo, riesgo, IS_v, str(final).replace('.', ',')

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            raw_json = json.loads(post_data)
            items = raw_json['items'] if isinstance(raw_json, dict) and 'items' in raw_json else raw_json
            df = pd.DataFrame(items)
            
            # Procesamos forzando la conversión a diccionario por fila (Anti-memoria)
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

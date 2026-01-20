def motor_baremacion_itacyl(row):
    """
    MOTOR DE BAREMACIÓN AGRONÓMICA - ESCENARIO A
    Versión 1.3.2 | Limpieza de caracteres (®) e Higiene de Bucle
    """
    # 0. PREPROCESAMIENTO
    nombre_raw = str(row.get('name', '')).strip()
    if not nombre_raw or nombre_raw.lower() == 'nan': 
        nombre_raw = "PRODUCTO SIN NOMBRE"
    
    # Normalización para búsqueda: Pasamos a Mayúsculas y quitamos símbolos como ®
    nombre_busqueda = re.sub(r'[^\w\s]', '', nombre_raw).upper()
    nombre = nombre_raw.upper() # Mantenemos el original para otras lógicas
    
    # Protección Excel con apóstrofo
    nombre_protegido = f"'{nombre_raw}"

    def clean(val):
        if pd.isna(val) or val is None: return 0.0
        try: 
            if isinstance(val, str): val = val.replace(',', '.')
            return float(val)
        except: return 0.0

    # Carga de variables analíticas
    n, p2o5, k2o = clean(row.get('n')), clean(row.get('p2o5')), clean(row.get('k2o'))
    nitricN, ammoniacalN = clean(row.get('nitricN')), clean(row.get('ammoniacalN'))
    organicMatter, s = clean(row.get('organicMatter')), clean(row.get('s'))
    materialSiexId = clean(row.get('materialSiexId')) 

    # 1. CÁLCULO DEL ÍNDICE DE SALINIDAD (IS_v) - HIGIENE TOTAL
    def calcular_is_fresco(n_f, p_f, k_f, nom_b):
        # Prioridad 1: Identificación por nombre (Valores Tabulados Rader)
        if any(k in nom_b for k in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]): return 15
        
        # Corrección Nitratos Potásicos (74) - TECNOPLUS capturado por nom_b limpia
        if any(k in nom_b for k in ["NITRATO POTASICO", "NIPO", "TECNOPLUS"]): return 74
        
        # Nitrato Amónico puro
        if "NITRATO AMONICO" in nom_b or "NAC" in nom_b: return 104
        
        if "UREA" in nom_b: return 75
        if any(k in nom_b for k in ["NITRATO DE CALCIO", "CALCINIT"]): return 85
        if "SULFATO POTASICO" in nom_b or "SOP" in nom_b: return 46
        if "SULFATO AMONICO" in nom_b: return 69
        if "CLORURO" in nom_b: return 116
        if "DAP" in nom_b: return 34
        if "MAP" in nom_b: return 30
        
        # Prioridad 2: Fórmula de Rader si no hay coincidencia
        calc = (n_f * 1.65) + (p_f * 0.5) + (k_f * 1.9)
        return int(round(min(max(calc, 5), 140)))

    # Asignación limpia del valor usando la versión "limpia" del nombre
    IS_v = calcular_is_fresco(n, p2o5, k2o, nombre_busqueda)

    # 2. CLASIFICACIÓN TÉCNICA
    siex_e_directos = [1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 19, 20, 21, 22]
    has_min = not pd.isna(row.get('yearPercent1'))
    is_siex_e = materialSiexId in siex_e_directos
    
    es_enm = has_min or is_siex_e
    es_cob = row.get('topDressing') is True
    is_liq = row.get('aggregateState') == 'L' or "SOLUB" in nombre
    
    if es_enm: tipo = "[E]"
    elif any(k in nombre for k in ["NITRATO DE CALCIO", "CALCINIT", "SOLUTECK"]): tipo = "[C,R]"
    elif es_cob: tipo = "[C,R]" if is_liq else "[C]"
    else: tipo = "[R]" if is_liq else "[F]"

    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    
    if es_enm or es_tec or any(k in nombre for k in kw_inh):
        return nombre_protegido, tipo, "Bajo", IS_v, "10,0"
    
    if tipo == "[C,R]" and any(k in nombre for k in ["NITRATO DE CALCIO", "SOLUTECK", "CALCINIT"]):
        return nombre_protegido, tipo, "Medio", IS_v, "9,5"

    # 3. ALGORITMO ACUMULATIVO
    baremo = 6.0
    if organicMatter > 20: baremo += 3.0
    if s > 2 or ammoniacalN > 10: baremo += 2.0
    
    micros_list = ['fe', 'zn', 'mn', 'cu', 'b', 'mo', 'mg']
    tiene_micros = any(clean(row.get(m)) > 0 for m in micros_list)
    if not tiene_micros:
        kw_mic = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO", "MG"]
        tiene_micros = any(k in nombre for k in kw_mic)
    if tiene_micros: baremo += 1.5

    npk_match = re.search(r'(\d+)-(\d+)-(\d+)', nombre)
    if p2o5 > 15: baremo += 1.0
    elif p2o5 == 0 and npk_match and float(npk_match.group(2)) > 15: baremo += 1.0
    if k2o > 15: baremo += 1.0
    elif k2o == 0 and npk_match and float(npk_match.group(3)) > 15: baremo += 1.0

    # 4. PENALIZACIONES
    es_fondo = (not es_cob) and (not es_enm)
    val_n_eval = n if es_fondo else nitricN
    riesgo = "Bajo"
    if 10 <= val_n_eval <= 20: 
        baremo -= 1.5
        riesgo = "Medio"
    elif val_n_eval > 20: 
        baremo -= 3.0
        riesgo = "Alto"

    if IS_v < 20: baremo += 1.5
    elif 20 <= IS_v < 40: baremo += 0.5
    elif 40 <= IS_v <= 60: baremo += 0.0
    elif 60 < IS_v <= 80: baremo -= 0.5
    elif 80 < IS_v <= 100: baremo -= 1.5
    elif IS_v > 100: baremo -= 3.0

    final = round(min(max(baremo, 1.0), 10.0), 1)
    return nombre_protegido, tipo, riesgo, IS_v, str(final).replace('.', ',')

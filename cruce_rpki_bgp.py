# Observatorio RPKI
import sys
import pandas as pd
import json
import radix
import time
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

# Constantes de los estados del algoritmo RFC 6811
ESTADO_VALIDO = "Valid"
ESTADO_INVALIDO_ASN = "Invalid: Origin Mismatch"
ESTADO_INVALIDO_LONG = "Invalid: Max-Length Exceeded"
ESTADO_DESCONOCIDO = "NotFound"

def construir_arbol_rpki(archivo_json_roas):
    print("Construyendo Árbol Radix en memoria con los ROAs...")
    rtree = radix.Radix()
    
    with open(archivo_json_roas, 'r') as f:
        datos = json.load(f)
        
    for roa in datos.get('roas', []):
        prefijo = roa.get('prefix')
        max_len = roa.get('maxLength')
        # Limpiamos el ASN (algunos validadores ponen "AS123", otros "123")
        asn = str(roa.get('asn')).replace('AS', '')
        
        # Añadimos el prefijo al árbol. 
        # Si ya existe (múltiples ROAs para la misma red), agregamos a la lista
        rnode = rtree.search_exact(prefijo)
        if not rnode:
            rnode = rtree.add(prefijo)
            rnode.data['roas'] = []
            
        rnode.data['roas'].append({
            'asn': asn,
            'max_length': int(max_len)
        })
        
    return rtree

def validar_ruta(rtree, prefijo_bgp, longitud_bgp, asn_bgp):
    # Buscamos todos los ROAs que cubran esta red BGP (búsqueda top-down en el árbol)
    rnodes = rtree.search_covering(prefijo_bgp)
    
    if not rnodes:
        return ESTADO_DESCONOCIDO
        
    # Variables de estado para el caso de múltiples ROAs
    estado_final = ESTADO_INVALIDO_ASN 
    fallo_longitud = False
    
    for rnode in rnodes:
        for roa in rnode.data['roas']:
            asn_coincide = (roa['asn'] == asn_bgp)
            longitud_valida = (int(longitud_bgp) <= roa['max_length'])
            
            if asn_coincide and longitud_valida:
                return ESTADO_VALIDO
            elif asn_coincide and not longitud_valida:
                fallo_longitud = True
                
    # Si llegamos aquí, no fue Valid. Determinamos el motivo exacto del Invalid.
    if fallo_longitud:
        return ESTADO_INVALIDO_LONG
    return ESTADO_INVALIDO_ASN

def ejecutar_cruce_global(archivo_bgp, archivo_roas, archivo_salida="internet_enriquecida_rpki.csv"):
    # 1. Cargar las leyes (ROAs)
    rtree = construir_arbol_rpki(archivo_roas)

    # 2. Cargar la realidad (Tabla BGP)
    print("Cargando tabla de enrutamiento BGP...")
    df_bgp = pd.read_csv(archivo_bgp)
    # Limpiar ASNs de la tabla BGP por seguridad
    df_bgp['ASN_BGP'] = df_bgp['ASN_BGP'].astype(str).str.replace('AS', '')

    print("Iniciando validación criptográfica masiva (ROV)...")
    t_inicio = time.time()

    # Aplicamos la función de validación a cada fila de Pandas
    df_bgp['Estado_RPKI'] = df_bgp.apply(
        lambda fila: validar_ruta(
            rtree,
            fila['Prefijo_BGP'],
            fila['Longitud_BGP'],
            fila['ASN_BGP']
        ),
        axis=1
    )

    t_fin = time.time()
    print(f"Cruce global finalizado en {t_fin - t_inicio:.2f} segundos.")

    # 3. Reporte de Resultados Científicos
    print("\n=== REPORTE DE CALIDAD GLOBAL DEL ENRUTAMIENTO ===")
    conteo = df_bgp['Estado_RPKI'].value_counts()
    porcentajes = df_bgp['Estado_RPKI'].value_counts(normalize=True).mul(100).round(2)

    resumen = pd.DataFrame({'Total_Prefijos': conteo, 'Porcentaje': porcentajes})
    print(resumen.to_string())

    df_bgp.to_csv(archivo_salida, index=False)
    print(f"\nDataset científico exportado a '{archivo_salida}'")
    return df_bgp

def exportar_invalidos(df_bgp, archivo_salida):
    estados_invalidos = [ESTADO_INVALIDO_ASN, ESTADO_INVALIDO_LONG]
    df_inv = (
        df_bgp[df_bgp['Estado_RPKI'].isin(estados_invalidos)]
        .sort_values(['Estado_RPKI', 'ASN_BGP'])
        .reset_index(drop=True)
    )
    df_inv.to_csv(archivo_salida, index=False)
    total = len(df_inv)
    n_asn = (df_inv['Estado_RPKI'] == ESTADO_INVALIDO_ASN).sum()
    n_len = (df_inv['Estado_RPKI'] == ESTADO_INVALIDO_LONG).sum()
    print(f"Prefijos inválidos exportados: {total:,} total "
          f"({n_asn:,} Origin Mismatch, {n_len:,} Max-Length) → {archivo_salida}")

def enviar_metricas_grafana(df_bgp, fecha="", ip_pushgateway="localhost:9091"):
    print("\nEmpujando resultados al repositorio de series temporales (Prometheus)...")
    registro = CollectorRegistry()

    metrica_rpki = Gauge('observatorio_rpki_rutas_globales',
                         'Cantidad de rutas en internet por estado RPKI',
                         ['estado', 'fecha'], registry=registro)

    conteo = df_bgp['Estado_RPKI'].value_counts()

    for estado, cantidad in conteo.items():
        etiqueta = estado.lower().replace(':', '').replace(' ', '_')
        metrica_rpki.labels(estado=etiqueta, fecha=fecha).set(cantidad)

    try:
        push_to_gateway(ip_pushgateway, job=f'observatorio_diario_{fecha}', registry=registro)
        print("Éxito: Datos inyectados en Grafana.")
    except Exception as e:
        print(f"Advertencia: No se pudo conectar al Pushgateway: {e}")

def enviar_tendencias_bgp(df_bgp, ip_pushgateway="localhost:9091"):
    """
    Pushea rutas BGP por estado (valid/invalid/notfound) y versión IP al job
    observatorio_tendencias_bgp (job fijo, sin fecha) para series temporales.
    """
    registro = CollectorRegistry()

    metrica = Gauge(
        'rpki_trend_rutas',
        'Rutas BGP por estado RPKI y versión IP — serie temporal',
        ['version', 'estado'],
        registry=registro
    )

    # Detectar versión IP desde el prefijo (rápido: ':' indica IPv6)
    df_bgp['IP_Version'] = df_bgp['Prefijo_BGP'].apply(
        lambda p: 'IPv6' if ':' in str(p) else 'IPv4'
    )

    etiquetas = {
        ESTADO_VALIDO:       'valid',
        ESTADO_INVALIDO_ASN: 'invalid_origin_mismatch',
        ESTADO_INVALIDO_LONG:'invalid_max_length',
        ESTADO_DESCONOCIDO:  'notfound',
    }

    for version in ['IPv4', 'IPv6']:
        df_v = df_bgp[df_bgp['IP_Version'] == version]
        conteo = df_v['Estado_RPKI'].value_counts()
        for estado_raw, etiqueta in etiquetas.items():
            metrica.labels(version=version, estado=etiqueta).set(
                int(conteo.get(estado_raw, 0))
            )

    try:
        push_to_gateway(ip_pushgateway, job='observatorio_tendencias_bgp', registry=registro)
        print("Éxito: tendencias BGP enviadas a Prometheus.")
    except Exception as e:
        print(f"Advertencia: No se pudo conectar al Pushgateway: {e}")


if __name__ == "__main__":
    archivo_bgp    = sys.argv[1] if len(sys.argv) > 1 else "tabla_bgp.csv"
    archivo_roas   = sys.argv[2] if len(sys.argv) > 2 else "vrps.json"
    archivo_salida = sys.argv[3] if len(sys.argv) > 3 else "internet_enriquecida_rpki.csv"
    fecha          = sys.argv[4] if len(sys.argv) > 4 else ""
    pushgateway    = sys.argv[5] if len(sys.argv) > 5 else "localhost:9091"
    invalidos_csv  = sys.argv[6] if len(sys.argv) > 6 else "prefijos_invalidos.csv"
    df_resultado = ejecutar_cruce_global(archivo_bgp, archivo_roas, archivo_salida)
    exportar_invalidos(df_resultado, invalidos_csv)
    enviar_metricas_grafana(df_resultado, fecha, pushgateway)
    enviar_tendencias_bgp(df_resultado, pushgateway)


"""
Exporta métricas de ROAs a Prometheus Pushgateway.

Lee el CSV procesado por analisis_roas.py y pushea:
  - rpki_roa_total / rpki_roa_holgados / rpki_roa_exactos / rpki_roa_pct_holgados
      por versión IP y fecha (job por snapshot, para comparación entre fechas)
  - rpki_roa_prefixlen_count / rpki_roa_maxlen_count
      por longitud × RIR × fecha (idem)
  - rpki_trend_roas_holgados / rpki_trend_roas_exactos
  - rpki_trend_prefixlen / rpki_trend_maxlen
  - rpki_trend_prefixlen_especificos  (>024 IPv4, >048 IPv6)
      sin label fecha, job fijo → serie temporal verdadera en Prometheus

Uso:
    python3 metricas_roas.py <vrps_procesados.csv> <FECHA> [pushgateway]
"""

import sys
import pandas as pd
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

ARCHIVO_CSV  = sys.argv[1] if len(sys.argv) > 1 else "vrps_procesados_para_grafico.csv"
FECHA        = sys.argv[2] if len(sys.argv) > 2 else ""
PUSHGATEWAY  = sys.argv[3] if len(sys.argv) > 3 else "localhost:9091"


def enviar_estadistica_general(df, fecha, pushgateway):
    registro = CollectorRegistry()
    m_total    = Gauge('rpki_roa_total',        'Total de ROAs por versión IP',             ['version', 'fecha'], registry=registro)
    m_holgados = Gauge('rpki_roa_holgados',     'ROAs holgados (maxLength > prefixLength)', ['version', 'fecha'], registry=registro)
    m_exactos  = Gauge('rpki_roa_exactos',      'ROAs exactos (maxLength = prefixLength)',  ['version', 'fecha'], registry=registro)
    m_pct      = Gauge('rpki_roa_pct_holgados', 'Porcentaje de ROAs holgados',              ['version', 'fecha'], registry=registro)

    for version in ['IPv4', 'IPv6']:
        d        = df[df['IP_Version'] == version]
        total    = len(d)
        holgados = int((d['Gap_Riesgo'] > 0).sum())
        exactos  = total - holgados
        pct      = round(holgados / total * 100, 1) if total else 0

        print(f"  {version}: total={total:,}  holgados={holgados:,} ({pct}%)  exactos={exactos:,}")
        m_total.labels(version=version,    fecha=fecha).set(total)
        m_holgados.labels(version=version, fecha=fecha).set(holgados)
        m_exactos.labels(version=version,  fecha=fecha).set(exactos)
        m_pct.labels(version=version,      fecha=fecha).set(pct)

    try:
        push_to_gateway(pushgateway, job=f'observatorio_estadistica_{fecha}', registry=registro)
        print("  Estadística general enviada a Prometheus.")
    except Exception as e:
        print(f"  Advertencia: no se pudo conectar al Pushgateway: {e}")


def enviar_histogramas(df, fecha, pushgateway):
    registro = CollectorRegistry()
    m_preflen = Gauge('rpki_roa_prefixlen_count', 'ROAs por longitud de prefijo',
                      ['version', 'longitud', 'trust_anchor', 'fecha'], registry=registro)
    m_maxlen  = Gauge('rpki_roa_maxlen_count',    'ROAs por MaxLength del ROA',
                      ['version', 'longitud', 'trust_anchor', 'fecha'], registry=registro)

    for version in ['IPv4', 'IPv6']:
        df_v = df[df['IP_Version'] == version]
        for columna, metrica in [('Prefijo_Base', m_preflen), ('Max_Length', m_maxlen)]:
            pivot = (
                df_v
                .groupby([columna, 'Trust_Anchor'])
                .size()
                .unstack(fill_value=0)
            )
            for longitud in pivot.index:
                for ta in pivot.columns:
                    metrica.labels(
                        version=version,
                        longitud=f"{int(longitud):03d}",
                        trust_anchor=ta,
                        fecha=fecha
                    ).set(int(pivot.loc[longitud, ta]))

    try:
        push_to_gateway(pushgateway, job=f'observatorio_histogramas_{fecha}', registry=registro)
        print("  Histogramas enviados a Prometheus.")
    except Exception as e:
        print(f"  Advertencia: no se pudo conectar al Pushgateway: {e}")


def enviar_tendencias(df, pushgateway):
    """Job fijo sin label fecha — Prometheus registra la evolución temporal real."""
    registro = CollectorRegistry()
    UMBRALES = {'IPv4': 24, 'IPv6': 48}

    m_preflen      = Gauge('rpki_trend_prefixlen',             'ROAs por prefixLen — serie temporal',        ['version', 'longitud', 'trust_anchor'],          registry=registro)
    m_maxlen       = Gauge('rpki_trend_maxlen',                'ROAs por MaxLength — serie temporal',        ['version', 'longitud', 'trust_anchor'],          registry=registro)
    m_holgados     = Gauge('rpki_trend_roas_holgados',         'ROAs holgados por versión y RIR',           ['version', 'trust_anchor'],                      registry=registro)
    m_exactos      = Gauge('rpki_trend_roas_exactos',          'ROAs exactos por versión y RIR',            ['version', 'trust_anchor'],                      registry=registro)
    m_especificos  = Gauge('rpki_trend_prefixlen_especificos', 'ROAs con prefixLen > umbral por versión/RIR', ['version', 'umbral', 'trust_anchor'],           registry=registro)

    for version in ['IPv4', 'IPv6']:
        df_v = df[df['IP_Version'] == version]
        rirs = df_v['Trust_Anchor'].unique()

        for columna, metrica in [('Prefijo_Base', m_preflen), ('Max_Length', m_maxlen)]:
            pivot = (
                df_v
                .groupby([columna, 'Trust_Anchor'])
                .size()
                .unstack(fill_value=0)
            )
            for longitud in pivot.index:
                for ta in pivot.columns:
                    metrica.labels(version=version, longitud=f"{int(longitud):03d}", trust_anchor=ta).set(
                        int(pivot.loc[longitud, ta])
                    )

        umbral = UMBRALES[version]
        label_umbral = f"gt{umbral:03d}"
        for ta in rirs:
            df_ta = df_v[df_v['Trust_Anchor'] == ta]
            m_holgados.labels(version=version, trust_anchor=ta).set(int((df_ta['Gap_Riesgo'] > 0).sum()))
            m_exactos.labels(version=version,  trust_anchor=ta).set(int((df_ta['Gap_Riesgo'] == 0).sum()))
            m_especificos.labels(version=version, umbral=label_umbral, trust_anchor=ta).set(
                int((df_ta['Prefijo_Base'] > umbral).sum())
            )

    try:
        push_to_gateway(pushgateway, job='observatorio_tendencias', registry=registro)
        print("  Tendencias enviadas a Prometheus.")
    except Exception as e:
        print(f"  Advertencia: no se pudo conectar al Pushgateway: {e}")


if __name__ == "__main__":
    print(f"Cargando {ARCHIVO_CSV}...")
    df = pd.read_csv(ARCHIVO_CSV)

    print("Enviando estadística general...")
    enviar_estadistica_general(df, FECHA, PUSHGATEWAY)

    print("Enviando histogramas de prefixLen/maxLen...")
    enviar_histogramas(df, FECHA, PUSHGATEWAY)

    print("Enviando tendencias (serie temporal)...")
    enviar_tendencias(df, PUSHGATEWAY)

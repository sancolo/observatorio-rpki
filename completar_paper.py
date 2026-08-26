import re
import pandas as pd
from pathlib import Path
from datetime import date

PAPER_INPUT = "paper_rpki.md"
PAPER_OUTPUT = "paper_rpki_completo.md"

ARCHIVO_BGP   = "internet_enriquecida_rpki.csv"
ARCHIVO_ROAS  = "vrps_procesados_para_grafico.csv"
ARCHIVO_TOP10 = "top_10_infractores.csv"


def metricas_bgp(archivo):
    df = pd.read_csv(archivo)
    total = len(df)
    conteo = df['Estado_RPKI'].value_counts()
    pct    = df['Estado_RPKI'].value_counts(normalize=True).mul(100).round(2)

    n_valid   = int(conteo.get('Valid', 0))
    n_nf      = int(conteo.get('NotFound', 0))
    n_ml      = int(conteo.get('Invalid: Max-Length Exceeded', 0))
    n_asn     = int(conteo.get('Invalid: Origin Mismatch', 0))
    n_invalid = n_ml + n_asn

    pct_invalid       = round(n_invalid / total * 100, 2) if total else 0
    pct_ml_of_invalid = round(n_ml / n_invalid * 100, 2) if n_invalid else 0
    pct_asn_of_invalid= round(n_asn / n_invalid * 100, 2) if n_invalid else 0
    ratio             = round(n_ml / n_asn, 1) if n_asn else 0

    return {
        'TOTAL_PREFIJOS':        f"{total:,}",
        'N_VALID':               f"{n_valid:,}",
        'PCT_VALID':             str(float(pct.get('Valid', 0))),
        'N_NOTFOUND':            f"{n_nf:,}",
        'PCT_NOTFOUND':          str(float(pct.get('NotFound', 0))),
        'N_INVALID_ML':          f"{n_ml:,}",
        'PCT_INVALID_ML':        str(float(pct.get('Invalid: Max-Length Exceeded', 0))),
        'N_INVALID_ASN':         f"{n_asn:,}",
        'PCT_INVALID_ASN':       str(float(pct.get('Invalid: Origin Mismatch', 0))),
        'N_INVALID_TOTAL':       f"{n_invalid:,}",
        'PCT_INVALID':           str(pct_invalid),
        'PCT_ML_OF_INVALID':     str(pct_ml_of_invalid),
        'PCT_ASN_OF_INVALID':    str(pct_asn_of_invalid),
        'RATIO_MAXLEN_VS_ORIGIN':str(ratio),
    }


def metricas_roas(archivo):
    df = pd.read_csv(archivo)
    total    = len(df)
    n_strict = int((df['Gap_Riesgo'] == 0).sum())
    n_loose  = int((df['Gap_Riesgo'] > 0).sum())

    df_loose_v4 = df[(df['IP_Version'] == 'IPv4') & (df['Gap_Riesgo'] > 0)]
    mediana_gap_v4  = df_loose_v4['Gap_Riesgo'].median() if not df_loose_v4.empty else 0
    subredes_prom   = int(2 ** mediana_gap_v4) if mediana_gap_v4 else 0

    return {
        'TOTAL_ROAS':             f"{total:,}",
        'N_STRICT':               f"{n_strict:,}",
        'PCT_STRICT':             str(round(n_strict / total * 100, 2)) if total else '0',
        'N_LOOSE':                f"{n_loose:,}",
        'PCT_LOOSE':              str(round(n_loose  / total * 100, 2)) if total else '0',
        'MEDIANA_GAP_IPV4':       str(int(mediana_gap_v4)),
        'SUBREDES_PROMEDIO_IPV4': f"{subredes_prom:,}",
    }


def metricas_top10(archivo):
    df = pd.read_csv(archivo).head(10).reset_index(drop=True)
    resultado = {}
    for i, fila in df.iterrows():
        n = i + 1
        resultado[f'ASN_{n}'] = str(fila['ASN'])
        resultado[f'ORG_{n}'] = str(fila['Organización'])
        resultado[f'N_{n}']   = f"{int(fila['Prefijos_Secuestrados_o_Erroneos']):,}"
        resultado[f'WEB_{n}'] = str(fila['Sitio_Web'])
    return resultado


def aplicar_reemplazos(texto, reemplazos):
    for clave, valor in reemplazos.items():
        texto = texto.replace(f'[{clave}]', valor)
    return texto


def placeholders_pendientes(texto):
    # Solo los tags simples en mayúsculas: [TOTAL_ROAS], [N_VALID], etc.
    # Ignora [INTERPRETAR: ...], [REFERENCIA], [AGREGAR ...], [X.X.X]
    return sorted(set(re.findall(r'\[[A-Z][A-Z0-9_]+\]', texto)))


if __name__ == "__main__":
    reemplazos = {}
    archivos_faltantes = []

    fuentes = [
        (ARCHIVO_BGP,   metricas_bgp,    "métricas BGP / estados RPKI"),
        (ARCHIVO_ROAS,  metricas_roas,   "análisis de ROAs"),
        (ARCHIVO_TOP10, metricas_top10,  "top 10 infractores"),
    ]

    for archivo, fn, descripcion in fuentes:
        if Path(archivo).exists():
            reemplazos.update(fn(archivo))
            print(f"  [ok] {archivo}  ({descripcion})")
        else:
            archivos_faltantes.append(archivo)
            print(f"  [--] {archivo} no encontrado — se omite {descripcion}")

    hoy = date.today().isoformat()
    reemplazos['FECHA']      = hoy
    reemplazos['YYYY-MM-DD'] = hoy
    reemplazos['YYYYMMDD']   = hoy.replace('-', '')

    texto = Path(PAPER_INPUT).read_text(encoding='utf-8')
    texto = aplicar_reemplazos(texto, reemplazos)
    Path(PAPER_OUTPUT).write_text(texto, encoding='utf-8')

    print(f"\nPaper generado: {PAPER_OUTPUT}")

    pendientes = placeholders_pendientes(texto)
    if pendientes:
        print("\nPlaceholders que requieren completar manualmente:")
        for tag in pendientes:
            print(f"  {tag}")
    else:
        print("Todos los placeholders fueron completados.")

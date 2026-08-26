import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.ticker as ticker
import seaborn as sns
from pathlib import Path

plt.style.use('seaborn-v0_8-whitegrid')
sns.set_context("paper", font_scale=1.2)


def _fecha_display(fecha):
    """Convierte YYYYMMDD o YYYYMMDD_HHMM a formato legible."""
    if fecha and len(fecha) == 13 and fecha[8] == '_' \
            and fecha[:8].isdigit() and fecha[9:].isdigit():
        return f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:8]} {fecha[9:11]}:{fecha[11:13]}"
    if fecha and len(fecha) == 8 and fecha.isdigit():
        return f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:]}"
    return fecha


def graficar_violin(df, ip_version, imagen_salida, fecha=""):
    df_v = df[(df['IP_Version'] == ip_version) & (df['Gap_Riesgo'] > 0)]
    if df_v.empty:
        print(f"Sin datos para {ip_version}, omitiendo violín.")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    sns.violinplot(
        data=df_v,
        x='Trust_Anchor',
        y='Gap_Riesgo',
        hue='Trust_Anchor',
        legend=False,
        palette='muted',
        inner='quartile',
        ax=ax
    )

    # Eje Y solo con valores enteros dentro del rango real de los datos
    gap_min = int(df_v['Gap_Riesgo'].min())
    gap_max = int(df_v['Gap_Riesgo'].max())
    # Para rangos grandes (IPv6) evitamos saturar el eje con un paso adaptativo
    paso = max(1, (gap_max - gap_min) // 20)
    ax.set_yticks(range(gap_min, gap_max + 1, paso))
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: str(int(x)) if x == int(x) else ''))

    ax.set_title(
        f'{ip_version} — Distribución de Loose ROAs por RIR',
        fontweight='bold', fontsize=14
    )
    ax.set_xlabel('Registro Regional de Internet (Trust Anchor)', fontweight='bold')
    ax.set_ylabel('Gap de Longitud ($MaxLen - PrefixLen$, bits)', fontweight='bold')

    n_roas = len(df_v)
    mediana = df_v['Gap_Riesgo'].median()
    ax.text(
        0.99, 0.98,
        f'ROAs holgados: {n_roas:,}  |  mediana: {mediana:.0f} bits',
        transform=ax.transAxes, ha='right', va='top',
        fontsize=9, color='#333333',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7)
    )

    if fecha:
        fig.text(0.01, 0.01, f"Fecha: {_fecha_display(fecha)}",
                 ha='left', va='bottom', fontsize=8, color='#888888')

    plt.tight_layout()
    plt.savefig(imagen_salida, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Violín {ip_version}: {imagen_salida}")


_BINS_LOG2   = [0, 1, 2, 4, 8, 16, 32, 64, 128]
_LABELS_LOG2 = ['1', '2', '3–4', '5–8', '9–16', '17–32', '33–64', '65–128']


def _agrupar_log2(series):
    """Agrupa gaps en bins potencia-de-2. Devuelve (serie_binada, etiquetas_con_datos)."""
    binada = pd.cut(series, bins=_BINS_LOG2, labels=_LABELS_LOG2, right=True)
    etiquetas_presentes = [l for l in _LABELS_LOG2 if (binada == l).any()]
    return binada, etiquetas_presentes


def graficar_heatmap(df, ip_version, imagen_salida, fecha=""):
    df_v = df[(df['IP_Version'] == ip_version) & (df['Gap_Riesgo'] > 0)].copy()
    if df_v.empty:
        print(f"Sin datos para {ip_version}, omitiendo heatmap.")
        return

    n_gaps_unicos = df_v['Gap_Riesgo'].nunique()
    usar_bins = n_gaps_unicos > 20  # IPv6 suele tener rango grande

    if usar_bins:
        df_v['Gap_Eje'], etiquetas_orden = _agrupar_log2(df_v['Gap_Riesgo'])
        df_v = df_v.dropna(subset=['Gap_Eje'])
        df_v['Gap_Eje'] = pd.Categorical(df_v['Gap_Eje'], categories=etiquetas_orden, ordered=True)
        pivot = (
            df_v
            .groupby(['Gap_Eje', 'Trust_Anchor'], observed=True)
            .size()
            .unstack(fill_value=0)
        )
        nota_eje = 'Gap (MaxLen − PrefixLen) — rangos en bits (escala log₂)'
    else:
        pivot = (
            df_v
            .groupby(['Gap_Riesgo', 'Trust_Anchor'])
            .size()
            .unstack(fill_value=0)
            .sort_index()
        )
        nota_eje = 'Gap (MaxLen − PrefixLen, bits)'

    altura = max(5, len(pivot.index) * 0.55)
    fig, ax = plt.subplots(figsize=(11, altura))

    sns.heatmap(
        pivot,
        ax=ax,
        cmap='YlOrRd',
        norm=mcolors.LogNorm(vmin=1, vmax=pivot.values.max()),
        linewidths=0.4,
        linecolor='#dddddd',
        annot=True,
        fmt='d',
        annot_kws={'size': 9},
        cbar_kws={'label': 'Cantidad de ROAs (escala logarítmica)'}
    )

    gap_min_real = int(df_v['Gap_Riesgo'].min())
    gap_max_real = int(df_v['Gap_Riesgo'].max())
    ax.set_title(
        f'{ip_version} — Gap de Longitud Máxima por RIR '
        f'(rango real: {gap_min_real}–{gap_max_real} bits)',
        fontweight='bold', fontsize=13
    )
    ax.set_xlabel('Registro Regional de Internet (Trust Anchor)', fontweight='bold')
    ax.set_ylabel(nota_eje, fontweight='bold')

    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(
        [str(int(v)) if not isinstance(v, str) else v for v in pivot.index],
        rotation=0, fontsize=9
    )

    total = int(pivot.values.sum())
    mediana = df_v['Gap_Riesgo'].median()
    ax.text(
        0.99, 0.02,
        f'ROAs holgados: {total:,}  |  mediana gap: {mediana:.0f} bits',
        transform=ax.transAxes, ha='right', va='bottom',
        fontsize=9, color='#333333',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8)
    )

    if fecha:
        fig.text(0.01, 0.01, f"Fecha: {_fecha_display(fecha)}",
                 ha='left', va='bottom', fontsize=8, color='#888888')

    plt.tight_layout()
    plt.savefig(imagen_salida, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Heatmap {ip_version}: {imagen_salida}")


def exportar_histograma_csv(df, ip_version, columna, csv_salida):
    df_v = df[df['IP_Version'] == ip_version]
    pivot = (
        df_v
        .groupby([columna, 'Trust_Anchor'])
        .size()
        .unstack(fill_value=0)
        .sort_index()
    )
    pivot['Total'] = pivot.sum(axis=1)
    pivot['Porcentaje'] = (pivot['Total'] / pivot['Total'].sum() * 100).round(2)
    pivot.index.name = 'Longitud_bits'
    pivot.to_csv(csv_salida)
    print(f"  CSV {ip_version} {columna}: {csv_salida}")


def graficar_histograma(df, ip_version, columna, imagen_salida, fecha=""):
    df_v = df[df['IP_Version'] == ip_version]
    if df_v.empty:
        print(f"Sin datos para {ip_version}, omitiendo histograma.")
        return

    # Tabla de conteos por longitud y Trust Anchor
    pivot = (
        df_v
        .groupby([columna, 'Trust_Anchor'])
        .size()
        .unstack(fill_value=0)
        .sort_index()
    )

    nombres = {
        'Prefijo_Base': ('Longitud del Prefijo (bits)', 'preflen'),
        'Max_Length':   ('MaxLength del ROA (bits)',    'maxlen'),
    }
    etiqueta_x, _ = nombres.get(columna, (columna, columna))

    # Ancho adaptativo al rango de valores, con límite para no generar figuras enormes
    n_valores = len(pivot.index)
    ancho = min(20, max(10, n_valores * 0.35))
    fig, ax = plt.subplots(figsize=(ancho, 6))

    # Barras apiladas por Trust Anchor
    colores = sns.color_palette('muted', n_colors=len(pivot.columns))
    bottom = pd.Series(0, index=pivot.index)
    for col, color in zip(pivot.columns, colores):
        ax.bar(pivot.index, pivot[col], bottom=bottom,
               label=col, color=color, width=0.8, edgecolor='white', linewidth=0.3)
        bottom = bottom + pivot[col]

    ax.set_title(
        f'{ip_version} — Distribución de {etiqueta_x} en ROAs por RIR',
        fontweight='bold', fontsize=14
    )
    ax.set_xlabel(etiqueta_x, fontweight='bold')
    ax.set_ylabel('Cantidad de ROAs', fontweight='bold')
    ax.legend(title='Trust Anchor', bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=9)

    # Eje X: limitar al rango real de los datos + margen visual mínimo
    ax.set_xlim(pivot.index.min() - 1, pivot.index.max() + 1)
    ax.set_xticks(pivot.index)
    ax.tick_params(axis='x', labelsize=8, rotation=45 if n_valores > 20 else 0)

    total = int(pivot.values.sum())
    mediana = df_v[columna].median()
    ax.text(
        0.01, 0.98,
        f'Total ROAs: {total:,}  |  mediana: {mediana:.0f} bits',
        transform=ax.transAxes, ha='left', va='top',
        fontsize=9, color='#333333',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8)
    )

    if fecha:
        fig.text(0.01, 0.01, f"Fecha: {_fecha_display(fecha)}",
                 ha='left', va='bottom', fontsize=8, color='#888888')

    plt.tight_layout()
    plt.savefig(imagen_salida, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Histograma {ip_version} {columna}: {imagen_salida}")


def _rir_slug(rir_nombre):
    return rir_nombre.lower().replace(' ', '_').replace('/', '_')


def graficar_histograma_rir(df, rir, ip_version, imagen_salida, fecha=""):
    df_v = df[(df['IP_Version'] == ip_version) & (df['Trust_Anchor'] == rir)]
    if df_v.empty:
        print(f"  Sin datos {rir}/{ip_version}, omitiendo.")
        return

    # Ancho adaptativo al rango de valores más largo entre los dos subplots
    n_vals_max = max(df_v['Prefijo_Base'].nunique(), df_v['Max_Length'].nunique())
    ancho = min(24, max(10, n_vals_max * 0.5))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(ancho, 9), constrained_layout=True)
    color = sns.color_palette('muted')[0]

    for ax, columna, etiqueta in [
        (ax1, 'Prefijo_Base', 'Longitud del Prefijo (bits)'),
        (ax2, 'Max_Length',   'MaxLength del ROA (bits)'),
    ]:
        conteo = df_v[columna].value_counts().sort_index()
        n_vals = len(conteo)
        ax.bar(conteo.index, conteo.values, color=color, edgecolor='white',
               linewidth=0.4, width=0.8)
        ax.set_xlabel(etiqueta, fontweight='bold')
        ax.set_ylabel('Cantidad de ROAs', fontweight='bold')

        # Eje X: limitar al rango real de los datos + margen visual mínimo
        ax.set_xlim(conteo.index.min() - 1, conteo.index.max() + 1)
        ax.set_xticks(conteo.index)
        if n_vals > 20:
            paso = max(2, n_vals // 15)
            etiquetas = [str(int(v)) if i % paso == 0 else ''
                         for i, v in enumerate(conteo.index)]
            ax.set_xticklabels(etiquetas, rotation=45, ha='right', fontsize=8)
        elif n_vals > 12:
            ax.tick_params(axis='x', labelsize=8, rotation=45)
        else:
            ax.tick_params(axis='x', labelsize=9, rotation=0)

        total = int(conteo.sum())
        mediana = df_v[columna].median()
        ax.text(0.99, 0.97, f'Total: {total:,}  |  mediana: {mediana:.0f} bits',
                transform=ax.transAxes, ha='right', va='top', fontsize=9,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))

    fig.suptitle(f'{rir} — {ip_version}: PrefixLen y MaxLength',
                 fontweight='bold', fontsize=14)

    if fecha:
        fig.text(0.01, 0.0, f"Fecha: {_fecha_display(fecha)}",
                 ha='left', va='bottom', fontsize=8, color='#888888')

    plt.savefig(imagen_salida, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Histograma RIR {rir}/{ip_version}: {imagen_salida}")


def exportar_histograma_rir_csv(df, rir, ip_version, columna, csv_salida):
    df_v = df[(df['IP_Version'] == ip_version) & (df['Trust_Anchor'] == rir)]
    conteo = df_v[columna].value_counts().sort_index()
    total = int(conteo.sum())
    resultado = pd.DataFrame({
        'Longitud_bits': conteo.index,
        'Cantidad':      conteo.values,
        'Porcentaje':    (conteo.values / total * 100).round(2) if total else 0,
    })
    resultado.to_csv(csv_salida, index=False)
    print(f"  CSV RIR {rir}/{ip_version}/{columna}: {csv_salida}")


def generar_histogramas_por_rir(df, base_salida, fecha=""):
    rirs = sorted(df['Trust_Anchor'].dropna().unique())
    base = Path(base_salida)
    print(f"Generando histogramas por RIR ({len(rirs)} RIRs)...")
    for rir in rirs:
        slug = _rir_slug(rir)
        for version in ['IPv4', 'IPv6']:
            ver_slug = version.lower()
            img = base.parent / f"{base.stem}_hist_rir_{slug}_{ver_slug}.png"
            graficar_histograma_rir(df, rir, version, str(img), fecha)
            for columna, col_slug in [('Prefijo_Base', 'preflen'), ('Max_Length', 'maxlen')]:
                csv_out = base.parent / f"{base.stem}_hist_rir_{slug}_{col_slug}_{ver_slug}.csv"
                exportar_histograma_rir_csv(df, rir, version, columna, str(csv_out))


def estadistica_general(df, fecha="", ip_pushgateway="localhost:9091"):
    """Imprime y pushea a Prometheus el resumen de ROAs por versión IP."""
    print("\n--- Estadística general de ROAs ---")
    try:
        from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
        registro = CollectorRegistry()
        m_total    = Gauge('rpki_roa_total',         'Total de ROAs por versión IP',             ['version', 'fecha'], registry=registro)
        m_holgados = Gauge('rpki_roa_holgados',      'ROAs holgados (maxLength > prefixLength)', ['version', 'fecha'], registry=registro)
        m_exactos  = Gauge('rpki_roa_exactos',       'ROAs exactos (maxLength = prefixLength)',  ['version', 'fecha'], registry=registro)
        m_pct      = Gauge('rpki_roa_pct_holgados',  'Porcentaje de ROAs holgados',              ['version', 'fecha'], registry=registro)
        push_disponible = True
    except ImportError:
        push_disponible = False

    for version in ['IPv4', 'IPv6']:
        d = df[df['IP_Version'] == version]
        total    = len(d)
        holgados = int((d['Gap_Riesgo'] > 0).sum())
        exactos  = total - holgados
        pct      = round(holgados / total * 100, 1) if total else 0

        print(f"  {version}:")
        print(f"    Total ROAs:    {total:,}")
        print(f"    Holgados:      {holgados:,}  ({pct}%)")
        print(f"    Exactos (g=0): {exactos:,}  ({100 - pct}%)")

        if push_disponible:
            m_total.labels(version=version,    fecha=fecha).set(total)
            m_holgados.labels(version=version, fecha=fecha).set(holgados)
            m_exactos.labels(version=version,  fecha=fecha).set(exactos)
            m_pct.labels(version=version,      fecha=fecha).set(pct)

    if push_disponible:
        try:
            push_to_gateway(ip_pushgateway, job=f'observatorio_estadistica_{fecha}', registry=registro)
            print("  Estadística general enviada a Prometheus.")
        except Exception as e:
            print(f"  Error al conectar con Pushgateway: {e}")


def enviar_histogramas_prometheus(df, fecha="", ip_pushgateway="localhost:9091"):
    try:
        from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
    except ImportError:
        print("prometheus_client no instalado, omitiendo push a Prometheus.")
        return

    registro = CollectorRegistry()

    metrica_preflen = Gauge(
        'rpki_roa_prefixlen_count',
        'Cantidad de ROAs por longitud de prefijo',
        ['version', 'longitud', 'trust_anchor', 'fecha'],
        registry=registro
    )
    metrica_maxlen = Gauge(
        'rpki_roa_maxlen_count',
        'Cantidad de ROAs por MaxLength del ROA',
        ['version', 'longitud', 'trust_anchor', 'fecha'],
        registry=registro
    )

    for version in ['IPv4', 'IPv6']:
        df_v = df[df['IP_Version'] == version]
        for columna, metrica in [('Prefijo_Base', metrica_preflen), ('Max_Length', metrica_maxlen)]:
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
        push_to_gateway(ip_pushgateway, job=f'observatorio_histogramas_{fecha}', registry=registro)
        print("Éxito: histogramas enviados a Prometheus.")
    except Exception as e:
        print(f"Error al conectar con Pushgateway: {e}")


def enviar_tendencias_prometheus(df, ip_pushgateway="localhost:9091"):
    """
    Pushea métricas SIN label fecha a un job fijo (observatorio_tendencias).
    Cada ejecución sobreescribe el job anterior, permitiendo que Prometheus
    registre el historial real como serie temporal verdadera.

    Métricas incluidas:
      rpki_trend_prefixlen        — ROAs por longitud de prefijo y RIR
      rpki_trend_maxlen           — ROAs por MaxLength y RIR
      rpki_trend_roas_holgados    — ROAs con Gap > 0 (maxLength > prefixLength) por versión y RIR
      rpki_trend_roas_exactos     — ROAs con Gap = 0 por versión y RIR
      rpki_trend_prefixlen_especificos — ROAs con prefixLen > umbral por versión y RIR
                                         (umbral: >024 para IPv4, >048 para IPv6)
    """
    try:
        from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
    except ImportError:
        print("prometheus_client no instalado, omitiendo tendencias.")
        return

    registro = CollectorRegistry()

    metrica_preflen = Gauge(
        'rpki_trend_prefixlen',
        'ROAs por longitud de prefijo — serie temporal',
        ['version', 'longitud', 'trust_anchor'],
        registry=registro
    )
    metrica_maxlen = Gauge(
        'rpki_trend_maxlen',
        'ROAs por MaxLength — serie temporal',
        ['version', 'longitud', 'trust_anchor'],
        registry=registro
    )
    metrica_holgados = Gauge(
        'rpki_trend_roas_holgados',
        'ROAs holgados (maxLength > prefixLength) por versión y RIR — serie temporal',
        ['version', 'trust_anchor'],
        registry=registro
    )
    metrica_exactos = Gauge(
        'rpki_trend_roas_exactos',
        'ROAs exactos (maxLength = prefixLength) por versión y RIR — serie temporal',
        ['version', 'trust_anchor'],
        registry=registro
    )
    metrica_especificos = Gauge(
        'rpki_trend_prefixlen_especificos',
        'ROAs con prefixLen por encima del umbral por versión y RIR — serie temporal',
        ['version', 'umbral', 'trust_anchor'],
        registry=registro
    )

    # Umbrales de "prefijos más específicos": /24 para IPv4, /48 para IPv6
    UMBRALES = {'IPv4': 24, 'IPv6': 48}

    for version in ['IPv4', 'IPv6']:
        df_v = df[df['IP_Version'] == version]
        rirs = df_v['Trust_Anchor'].unique()

        # prefixlen y maxlen por longitud × RIR
        for columna, metrica in [('Prefijo_Base', metrica_preflen), ('Max_Length', metrica_maxlen)]:
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
                        trust_anchor=ta
                    ).set(int(pivot.loc[longitud, ta]))

        # holgados y exactos por RIR
        for ta in rirs:
            df_ta = df_v[df_v['Trust_Anchor'] == ta]
            metrica_holgados.labels(version=version, trust_anchor=ta).set(
                int((df_ta['Gap_Riesgo'] > 0).sum())
            )
            metrica_exactos.labels(version=version, trust_anchor=ta).set(
                int((df_ta['Gap_Riesgo'] == 0).sum())
            )

        # prefijos más específicos que el umbral
        umbral = UMBRALES[version]
        label_umbral = f"gt{umbral:03d}"
        for ta in rirs:
            df_ta = df_v[df_v['Trust_Anchor'] == ta]
            n = int((df_ta['Prefijo_Base'] > umbral).sum())
            metrica_especificos.labels(version=version, umbral=label_umbral, trust_anchor=ta).set(n)

    try:
        push_to_gateway(ip_pushgateway, job='observatorio_tendencias', registry=registro)
        print("Éxito: tendencias enviadas a Prometheus.")
    except Exception as e:
        print(f"Error al conectar con Pushgateway: {e}")


def generar_todos(archivo_csv, base_salida, fecha="", pushgateway="localhost:9091"):
    df = pd.read_csv(archivo_csv)

    base = Path(base_salida)

    def p(sufijo):
        return base.parent / f"{base.stem}{sufijo}"

    print("Generando gráficos de violín...")
    graficar_violin(df, 'IPv4', p('_violin_ipv4.png'), fecha)
    graficar_violin(df, 'IPv6', p('_violin_ipv6.png'), fecha)

    print("Generando heatmaps discretos...")
    graficar_heatmap(df, 'IPv4', p('_heatmap_ipv4.png'), fecha)
    graficar_heatmap(df, 'IPv6', p('_heatmap_ipv6.png'), fecha)

    print("Generando histogramas de longitud de prefijo...")
    graficar_histograma(df, 'IPv4', 'Prefijo_Base', p('_hist_preflen_ipv4.png'), fecha)
    graficar_histograma(df, 'IPv6', 'Prefijo_Base', p('_hist_preflen_ipv6.png'), fecha)
    exportar_histograma_csv(df, 'IPv4', 'Prefijo_Base', p('_hist_preflen_ipv4.csv'))
    exportar_histograma_csv(df, 'IPv6', 'Prefijo_Base', p('_hist_preflen_ipv6.csv'))

    print("Generando histogramas de MaxLength...")
    graficar_histograma(df, 'IPv4', 'Max_Length', p('_hist_maxlen_ipv4.png'), fecha)
    graficar_histograma(df, 'IPv6', 'Max_Length', p('_hist_maxlen_ipv6.png'), fecha)
    exportar_histograma_csv(df, 'IPv4', 'Max_Length', p('_hist_maxlen_ipv4.csv'))
    exportar_histograma_csv(df, 'IPv6', 'Max_Length', p('_hist_maxlen_ipv6.csv'))

    print("Generando histogramas por RIR...")
    generar_histogramas_por_rir(df, base_salida, fecha)

    estadistica_general(df, fecha, pushgateway)

    print("Enviando histogramas a Prometheus...")
    enviar_histogramas_prometheus(df, fecha, pushgateway)

    print("Enviando tendencias a Prometheus...")
    enviar_tendencias_prometheus(df, pushgateway)


if __name__ == "__main__":
    archivo_csv  = sys.argv[1] if len(sys.argv) > 1 else "vrps_procesados_para_grafico.csv"
    base_salida  = sys.argv[2] if len(sys.argv) > 2 else "distribucion_loose_roas"
    fecha        = sys.argv[3] if len(sys.argv) > 3 else ""
    pushgateway  = sys.argv[4] if len(sys.argv) > 4 else "localhost:9091"
    generar_todos(archivo_csv, base_salida, fecha, pushgateway)

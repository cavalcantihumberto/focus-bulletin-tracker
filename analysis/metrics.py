"""
Módulo de análise das expectativas do Boletim Focus.
Calcula revisões semanais, dispersão e métricas resumidas.
"""

import pandas as pd
import numpy as np

from utils.logger import get_logger

logger = get_logger(__name__)


def calcular_revisoes(df: pd.DataFrame, coluna: str = "Mediana") -> pd.DataFrame:
    """
    Acrescenta colunas de revisão semanal ao DataFrame.

    Colunas adicionadas:
        Revisao           : diferença absoluta vs observação anterior
        RevisaoPercentual : variação percentual vs observação anterior
    """
    df = df.copy().sort_values("Data").reset_index(drop=True)
    df["Revisao"] = df[coluna].diff()
    df["RevisaoPercentual"] = df[coluna].pct_change() * 100
    return df


def calcular_dispersao(df: pd.DataFrame) -> pd.DataFrame:
    """
    Acrescenta a coluna Amplitude (Maximo - Minimo) como medida de dispersão
    entre os participantes do Focus.
    """
    df = df.copy()
    df["Amplitude"] = df["Maximo"] - df["Minimo"]
    return df


def sinalizar_revisoes_relevantes(
    df: pd.DataFrame,
    threshold: float = 0.1,
    coluna_revisao: str = "Revisao",
) -> pd.DataFrame:
    """
    Adiciona coluna booleana 'RevisaoRelevante' para semanas onde a revisão
    absoluta da mediana ultrapassou o threshold configurado.
    """
    df = df.copy()
    df["RevisaoRelevante"] = df[coluna_revisao].abs() > threshold
    return df


def resumo_estatistico(df: pd.DataFrame) -> dict:
    """
    Retorna dicionário com estatísticas do período selecionado.
    Retorna dicionário vazio se o DataFrame estiver vazio.
    """
    if df.empty:
        return {}

    primeira_mediana = df["Mediana"].iloc[0] if len(df) > 0 else np.nan
    ultima_mediana = df["Mediana"].iloc[-1] if len(df) > 0 else np.nan

    return {
        "Última Mediana": ultima_mediana,
        "Variação no Período": ultima_mediana - primeira_mediana,
        "Máx. Dispersão": df["Amplitude"].max() if "Amplitude" in df.columns else None,
        "Revisão Máxima": df["Revisao"].max() if "Revisao" in df.columns else None,
        "Revisão Mínima": df["Revisao"].min() if "Revisao" in df.columns else None,
        "Desvio Padrão Médio": df["DesvioPadrao"].mean() if "DesvioPadrao" in df.columns else None,
        "Semanas Analisadas": len(df),
    }


def ultimas_semanas(df: pd.DataFrame, n: int = 8) -> pd.DataFrame:
    """Retorna as n observações mais recentes, ordenadas da mais recente para a mais antiga."""
    return df.copy().sort_values("Data", ascending=False).head(n)


def calcular_erro_consenso(
    df_projecoes: pd.DataFrame,
    df_realizados: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compara medianas históricas do Focus com valores efetivamente realizados.

    Para cada ano com valor realizado disponível, extrai a mediana projetada
    nos horizontes 104, 78, 52, 26, 13 e 4 semanas antes de 31/dezembro do ano.

    Retorna DataFrame com colunas:
        ano, horizonte_semanas, data_projecao, mediana_projetada,
        valor_realizado, erro, erro_absoluto
    """
    _COLS = [
        "ano", "horizonte_semanas", "data_projecao",
        "mediana_projetada", "valor_realizado", "erro", "erro_absoluto",
    ]

    if df_realizados.empty or df_projecoes.empty:
        return pd.DataFrame(columns=_COLS)

    HORIZONTES = [104, 78, 52, 26, 13, 4]

    df_proj = df_projecoes.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_proj["Data"]):
        df_proj["Data"] = pd.to_datetime(df_proj["Data"], errors="coerce")
    df_proj = df_proj.dropna(subset=["Data", "Mediana"])

    registros = []
    for _, row_real in df_realizados.iterrows():
        try:
            ano = int(row_real["ano"])
            valor_realizado = float(row_real["valor_realizado"])
        except (ValueError, TypeError):
            continue

        data_ref = pd.Timestamp(f"{ano}-12-31")
        df_ano = df_proj[df_proj["DataReferencia"].astype(str) == str(ano)]

        if df_ano.empty:
            continue

        for horizonte in HORIZONTES:
            data_alvo = data_ref - pd.Timedelta(weeks=horizonte)
            df_antes = df_ano[df_ano["Data"] <= data_alvo]
            if df_antes.empty:
                continue

            row_proj = df_antes.loc[df_antes["Data"].idxmax()]
            mediana = float(row_proj["Mediana"])
            erro = mediana - valor_realizado

            registros.append({
                "ano": ano,
                "horizonte_semanas": horizonte,
                "data_projecao": row_proj["Data"],
                "mediana_projetada": mediana,
                "valor_realizado": valor_realizado,
                "erro": erro,
                "erro_absoluto": abs(erro),
            })

    return pd.DataFrame(registros) if registros else pd.DataFrame(columns=_COLS)


def calcular_pipeline_completo(
    df: pd.DataFrame,
    threshold_revisao: float = 0.1,
) -> pd.DataFrame:
    """
    Executa todas as transformações analíticas em sequência:
      1. Calcula amplitude (dispersão)
      2. Calcula revisões semanais
      3. Sinaliza revisões relevantes acima do threshold

    Retorna DataFrame enriquecido com colunas: Amplitude, Revisao,
    RevisaoPercentual, RevisaoRelevante.
    """
    if df.empty:
        return df

    indicador = df["Indicador"].iloc[0] if "Indicador" in df.columns else "?"
    ano = df["DataReferencia"].iloc[0] if "DataReferencia" in df.columns else "?"
    n = len(df)

    logger.info("Calculando métricas: %s/%s — %d linhas", indicador, ano, n)

    if n < 2:
        logger.warning(
            "DataFrame com %d linha(s) para %s/%s — revisão semanal não calculável",
            n, indicador, ano,
        )

    try:
        df = calcular_dispersao(df)
        df = calcular_revisoes(df)
        df = sinalizar_revisoes_relevantes(df, threshold=threshold_revisao)
    except Exception as e:
        logger.error(
            "Erro inesperado no cálculo de métricas para %s/%s: %s",
            indicador, ano, e,
            exc_info=True,
        )
        raise

    return df

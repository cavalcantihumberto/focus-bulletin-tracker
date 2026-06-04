"""
Testes do módulo analysis/metrics.py.

Cobertura:
  - Cálculo de revisão semanal (diff)
  - Valor NaN na primeira linha de revisão
  - Cálculo de amplitude (Maximo - Minimo)
  - Campos obrigatórios do resumo estatístico
  - Quantidade de linhas retornada por ultimas_semanas
  - Robustez com DataFrame vazio
"""

import numpy as np
import pandas as pd
import pytest

from analysis.metrics import (
    calcular_dispersao,
    calcular_erro_consenso,
    calcular_pipeline_completo,
    calcular_revisoes,
    resumo_estatistico,
    ultimas_semanas,
)


def test_calculo_revisao_semanal(df_ipca):
    """Revisão deve ser exatamente a diferença entre medianas consecutivas."""
    df = calcular_revisoes(df_ipca)
    revisao_esperada = df_ipca["Mediana"].iloc[1] - df_ipca["Mediana"].iloc[0]
    assert abs(df["Revisao"].iloc[1] - revisao_esperada) < 1e-9, (
        f"Revisão esperada: {revisao_esperada:.4f}, obtida: {df['Revisao'].iloc[1]:.4f}"
    )


def test_revisao_primeira_linha_nula(df_ipca):
    """Primeira linha deve ter Revisao == NaN pois não existe semana anterior."""
    df = calcular_revisoes(df_ipca)
    assert pd.isna(df["Revisao"].iloc[0]), (
        f"Esperado NaN na primeira revisão, obtido: {df['Revisao'].iloc[0]}"
    )


def test_calculo_amplitude(df_ipca):
    """Amplitude deve ser exatamente Maximo − Minimo para cada observação."""
    df = calcular_dispersao(df_ipca)
    esperado = (df_ipca["Maximo"] - df_ipca["Minimo"]).values
    calculado = df["Amplitude"].values
    np.testing.assert_allclose(
        calculado, esperado, rtol=1e-10,
        err_msg="Amplitude não corresponde a Maximo - Minimo",
    )


def test_resumo_estatistico_tem_campos(df_ipca):
    """resumo_estatistico deve retornar os três campos exibidos nas métricas do dashboard."""
    df = calcular_pipeline_completo(df_ipca)
    resumo = resumo_estatistico(df)
    campos_obrigatorios = ["Última Mediana", "Variação no Período", "Máx. Dispersão"]
    ausentes = [c for c in campos_obrigatorios if c not in resumo]
    assert not ausentes, f"Campos ausentes no resumo estatístico: {ausentes}"


def test_ultimas_n_semanas(df_ipca):
    """ultimas_semanas deve retornar exatamente n linhas para qualquer n <= len(df)."""
    for n in [3, 5, 8]:
        resultado = ultimas_semanas(df_ipca, n=n)
        assert len(resultado) == n, (
            f"n={n}: esperado {n} linhas, obtido {len(resultado)}"
        )


def test_dados_vazios_nao_quebra():
    """Todas as funções analíticas devem suportar DataFrame vazio sem lançar exceção."""
    df_vazio = pd.DataFrame(columns=[
        "Indicador", "Data", "Mediana", "Media",
        "DesvioPadrao", "Minimo", "Maximo", "baseCalculo",
    ])

    # Nenhuma dessas chamadas deve lançar exceção
    df_rev = calcular_revisoes(df_vazio)
    assert df_rev.empty

    df_disp = calcular_dispersao(df_vazio)
    assert df_disp.empty

    assert resumo_estatistico(df_vazio) == {}

    df_ult = ultimas_semanas(df_vazio, n=8)
    assert df_ult.empty

    df_pipe = calcular_pipeline_completo(df_vazio)
    assert df_pipe.empty


def test_erro_consenso_calculo_correto():
    """Erro deve ser exatamente mediana_projetada - valor_realizado (tolerância 1e-9)."""
    # Para 2022, 4 semanas antes de 31/dez = ~3/dez. Projeção em 01/dez (≤ alvo) = mediana 5.5
    df_projecoes = pd.DataFrame({
        "Indicador": ["IPCA"] * 3,
        "Data": pd.to_datetime(["2022-01-07", "2022-06-03", "2022-12-01"]),
        "DataReferencia": ["2022"] * 3,
        "Mediana": [4.0, 5.0, 5.5],
        "Media": [4.1, 5.1, 5.6],
    })
    df_realizados = pd.DataFrame({
        "ano": [2022],
        "valor_realizado": [5.79],
        "fonte": ["test"],
    })

    resultado = calcular_erro_consenso(df_projecoes, df_realizados)

    assert not resultado.empty, "Resultado não deve ser vazio"

    row_4w = resultado[resultado["horizonte_semanas"] == 4]
    assert not row_4w.empty, "Deve haver resultado para horizonte de 4 semanas"

    esperado_erro = 5.5 - 5.79
    obtido_erro = row_4w.iloc[0]["erro"]
    assert abs(obtido_erro - esperado_erro) < 1e-9, (
        f"Erro esperado {esperado_erro:.6f}, obtido {obtido_erro:.6f}"
    )
    assert abs(row_4w.iloc[0]["erro_absoluto"] - abs(esperado_erro)) < 1e-9


def test_erro_consenso_sem_dados_realizados():
    """Deve retornar DataFrame vazio sem levantar exceção quando df_realizados está vazio."""
    df_projecoes = pd.DataFrame({
        "Indicador": ["IPCA"],
        "Data": pd.to_datetime(["2022-06-03"]),
        "DataReferencia": ["2022"],
        "Mediana": [4.5],
        "Media": [4.6],
    })
    df_realizados = pd.DataFrame(columns=["ano", "valor_realizado", "fonte"])

    resultado = calcular_erro_consenso(df_projecoes, df_realizados)
    assert resultado.empty, "Deve retornar DataFrame vazio quando realizados está vazio"

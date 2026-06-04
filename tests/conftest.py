"""
Fixtures compartilhadas entre os módulos de teste.

Os DataFrames simulam o retorno processado de buscar_expectativas() —
já com baseCalculo filtrado, datas convertidas para Timestamp e valores numéricos.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Garante que o pacote raiz do projeto esteja no sys.path independente de onde
# o pytest é invocado.
sys.path.insert(0, str(Path(__file__).parent.parent))

N = 20  # número de semanas em cada fixture


def _semanas(n: int, inicio: str = "2025-01-03") -> list:
    base = pd.Timestamp(inicio)
    return [base + pd.Timedelta(weeks=i) for i in range(n)]


@pytest.fixture
def df_ipca():
    """IPCA 2025 — mediana entre 4,50% e 5,07%, tendência de alta gradual."""
    datas = _semanas(N)
    medianas = [round(4.50 + i * 0.03, 2) for i in range(N)]
    return pd.DataFrame({
        "Indicador": ["IPCA"] * N,
        "Data": datas,
        "DataReferencia": ["2025"] * N,
        "baseCalculo": [0] * N,
        "Mediana": medianas,
        "Media": [round(m + 0.05, 2) for m in medianas],
        "DesvioPadrao": [round(0.35 + i * 0.005, 3) for i in range(N)],
        "Minimo": [round(m - 0.90, 2) for m in medianas],
        "Maximo": [round(m + 1.20, 2) for m in medianas],
    })


@pytest.fixture
def df_selic():
    """Selic 2025 — mediana entre 12,50% e 11,55%, ciclo de queda."""
    datas = _semanas(N)
    medianas = [round(12.50 - i * 0.05, 2) for i in range(N)]
    return pd.DataFrame({
        "Indicador": ["Selic"] * N,
        "Data": datas,
        "DataReferencia": ["2025"] * N,
        "baseCalculo": [0] * N,
        "Mediana": medianas,
        "Media": [round(m + 0.02, 2) for m in medianas],
        "DesvioPadrao": [0.40] * N,
        "Minimo": [round(m - 0.50, 2) for m in medianas],
        "Maximo": [round(m + 0.50, 2) for m in medianas],
    })


@pytest.fixture
def df_pib():
    """PIB Total 2025 — mediana entre 2,00% e 2,38%, expansão gradual."""
    datas = _semanas(N)
    medianas = [round(2.00 + i * 0.02, 2) for i in range(N)]
    return pd.DataFrame({
        "Indicador": ["PIB Total"] * N,
        "Data": datas,
        "DataReferencia": ["2025"] * N,
        "baseCalculo": [0] * N,
        "Mediana": medianas,
        "Media": [round(m - 0.03, 2) for m in medianas],
        "DesvioPadrao": [0.20] * N,
        "Minimo": [round(m - 0.40, 2) for m in medianas],
        "Maximo": [round(m + 0.50, 2) for m in medianas],
    })


@pytest.fixture
def df_cambio():
    """Câmbio 2025 — mediana entre R$5,10 e R$5,29, depreciação suave."""
    datas = _semanas(N)
    medianas = [round(5.10 + i * 0.01, 2) for i in range(N)]
    return pd.DataFrame({
        "Indicador": ["Câmbio"] * N,
        "Data": datas,
        "DataReferencia": ["2025"] * N,
        "baseCalculo": [0] * N,
        "Mediana": medianas,
        "Media": [round(m + 0.08, 2) for m in medianas],
        "DesvioPadrao": [0.25] * N,
        "Minimo": [round(m - 0.30, 2) for m in medianas],
        "Maximo": [round(m + 0.50, 2) for m in medianas],
    })

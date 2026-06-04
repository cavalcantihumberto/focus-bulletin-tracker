"""
Testes do módulo data/fetcher.py.

Cobertura:
  - Conectividade real com a API BCB Olinda  (integração)
  - Schema das colunas obrigatórias
  - Filtragem de baseCalculo
  - Qualidade dos dados (nulos, faixa de valores)
  - Ordenação cronológica
  - Criação de cache em disco
"""

import pandas as pd
import pytest
import requests
from unittest.mock import MagicMock, patch

from data.fetcher import (
    BASE_URL,
    ENDPOINT,
    buscar_expectativas,
    _limpar_dataframe,
)


# ---------------------------------------------------------------------------
# Integração — requer conexão com a internet
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_api_bcb_acessivel():
    """A API BCB Olinda deve responder HTTP 200 para uma consulta mínima."""
    url = f"{BASE_URL}{ENDPOINT}?$top=1&$format=json"
    resp = requests.get(url, timeout=15)
    assert resp.status_code == 200, (
        f"API BCB retornou {resp.status_code} em vez de 200. "
        "Verifique conectividade ou disponibilidade do serviço."
    )


# ---------------------------------------------------------------------------
# Testes de schema e qualidade — usam fixtures do conftest
# ---------------------------------------------------------------------------

def test_retorno_tem_colunas_obrigatorias(df_ipca):
    """DataFrame deve conter as 7 colunas do schema padrão do Boletim Focus."""
    obrigatorias = {
        "Indicador", "Data", "Mediana", "Media",
        "DesvioPadrao", "Minimo", "Maximo",
    }
    ausentes = obrigatorias - set(df_ipca.columns)
    assert not ausentes, f"Colunas ausentes: {ausentes}"


def test_filtro_base_calculo():
    """_limpar_dataframe deve manter apenas linhas com baseCalculo == 0."""
    df_bruto = pd.DataFrame({
        "Indicador": ["IPCA"] * 4,
        "Data": ["2025-01-03", "2025-01-10", "2025-01-17", "2025-01-24"],
        "DataReferencia": ["2025"] * 4,
        "baseCalculo": [0, 1, 0, 1],  # duas linhas suavizadas (1) devem ser removidas
        "Mediana": ["4.50", "4.50", "4.53", "4.53"],
        "Media": ["4.55", "4.55", "4.58", "4.58"],
        "DesvioPadrao": ["0.35"] * 4,
        "Minimo": ["3.60"] * 4,
        "Maximo": ["5.70"] * 4,
    })
    resultado = _limpar_dataframe(df_bruto)
    assert (resultado["baseCalculo"] == 0).all(), "Linhas com baseCalculo != 0 não foram removidas"
    assert len(resultado) == 2, f"Esperado 2 linhas, obtido {len(resultado)}"


def test_sem_valores_nulos_em_mediana(df_ipca):
    """Coluna Mediana não deve conter NaN no DataFrame processado."""
    nulos = df_ipca["Mediana"].isna().sum()
    assert nulos == 0, f"Encontrados {nulos} valores nulos em Mediana"


def test_mediana_dentro_de_range_realista(df_ipca):
    """Mediana do IPCA deve estar entre 0% e 20% — sanity check de escala."""
    fora = df_ipca[~df_ipca["Mediana"].between(0, 20)]
    assert fora.empty, (
        f"Encontrados {len(fora)} valores de Mediana fora do intervalo [0, 20]: "
        f"{fora['Mediana'].tolist()}"
    )


def test_datas_em_ordem_cronologica():
    """_limpar_dataframe deve ordenar datas em ordem crescente mesmo com entrada embaralhada."""
    df_embaralhado = pd.DataFrame({
        "Indicador": ["IPCA"] * 5,
        "Data": ["2025-03-07", "2025-01-03", "2025-05-02", "2025-02-07", "2025-04-04"],
        "DataReferencia": ["2025"] * 5,
        "baseCalculo": [0] * 5,
        "Mediana": [4.60, 4.50, 4.68, 4.53, 4.65],
        "Media": [4.65, 4.55, 4.73, 4.58, 4.70],
        "DesvioPadrao": [0.35] * 5,
        "Minimo": [3.70] * 5,
        "Maximo": [5.80] * 5,
    })
    resultado = _limpar_dataframe(df_embaralhado)
    datas = resultado["Data"].tolist()
    assert datas == sorted(datas), "Datas não estão em ordem cronológica crescente"


# ---------------------------------------------------------------------------
# Cache em disco
# ---------------------------------------------------------------------------

def test_cache_criado_apos_busca(tmp_path, monkeypatch):
    """Arquivo CSV de cache deve ser criado em disco após busca bem-sucedida."""
    monkeypatch.setattr("data.fetcher.CACHE_DIR", tmp_path)

    registros = [
        {
            "Indicador": "IPCA",
            "Data": f"2025-0{i + 1}-07",
            "DataReferencia": "2025",
            "baseCalculo": 0,
            "Mediana": round(4.50 + i * 0.05, 2),
            "Media": round(4.55 + i * 0.05, 2),
            "DesvioPadrao": 0.35,
            "Minimo": 3.60,
            "Maximo": 5.70,
        }
        for i in range(5)
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": registros}
    mock_resp.raise_for_status.return_value = None

    with patch("data.fetcher.requests.get", return_value=mock_resp):
        buscar_expectativas("IPCA", "2025", forcar_atualizacao=True)

    cache_file = tmp_path / "IPCA_2025.csv"
    assert cache_file.exists(), "Arquivo CSV de cache não foi criado"

    df_cache = pd.read_csv(cache_file)
    assert len(df_cache) == 5, f"Esperado 5 linhas no cache, obtido {len(df_cache)}"

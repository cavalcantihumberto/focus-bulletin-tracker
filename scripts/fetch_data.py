"""
Pipeline de dados — Focus Bulletin Tracker.

Busca expectativas do Boletim Focus diretamente da API BCB para todos os
indicadores e anos disponíveis, e salva como Parquet em data/processed/.

Executado automaticamente via GitHub Actions toda segunda-feira às 12:00 UTC.
Para rodar manualmente:
    python scripts/fetch_data.py
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

# ── Adiciona a raiz do projeto ao sys.path ────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pandas as pd
import requests
import truststore

truststore.inject_into_ssl()

from data.fetcher import (
    BASE_URL,
    CAMPOS,
    CAMPOS_TOP5,
    ENDPOINT,
    ENDPOINT_TOP5,
    INDICADORES,
    _limpar_dataframe,
)
from utils.logger import get_logger

logger = get_logger("scripts.fetch_data")

PROCESSED_DIR = _ROOT / "data" / "processed"
SCRIPT_VERSION = "1.0.0"
ANOS = [str(ano) for ano in range(2022, 2030)]
_DELAY = 0.25  # segundos entre requisições — seja gentil com a API do BCB


# ---------------------------------------------------------------------------
# Funções de coleta (sem cache SQLite)
# ---------------------------------------------------------------------------

def _buscar_anual(indicador: str, ano: str) -> pd.DataFrame:
    """Consulta ExpectativasMercadoAnuais sem passar pelo cache local."""
    filtro = f"Indicador eq '{indicador}' and DataReferencia eq '{ano}'"
    qs = (
        f"$filter={quote(filtro)}"
        f"&$select={quote(','.join(CAMPOS))}"
        f"&$format=json"
        f"&$top=10000"
    )
    url = BASE_URL + ENDPOINT + "?" + qs
    resp = requests.get(url, timeout=30, verify=True)
    resp.raise_for_status()
    registros = resp.json().get("value", [])
    if not registros:
        return pd.DataFrame(columns=CAMPOS)
    return _limpar_dataframe(pd.DataFrame(registros))


def _buscar_cambio_top5(ano: str) -> pd.DataFrame:
    """Fallback para Câmbio: ExpectativasMercadoTop5Anuais (tipoCalculo='M')."""
    filtro = (
        f"Indicador eq 'Câmbio' and DataReferencia eq '{ano}'"
        f" and tipoCalculo eq 'M'"
    )
    qs = (
        f"$filter={quote(filtro)}"
        f"&$select={quote(','.join(CAMPOS_TOP5))}"
        f"&$format=json"
        f"&$top=10000"
    )
    url = BASE_URL + ENDPOINT_TOP5 + "?" + qs
    resp = requests.get(url, timeout=30, verify=True)
    resp.raise_for_status()
    registros = resp.json().get("value", [])
    if not registros:
        return pd.DataFrame(columns=CAMPOS_TOP5)
    return _limpar_dataframe(pd.DataFrame(registros))


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    inicio_total = time.perf_counter()
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    metadata: dict = {
        "ultima_atualizacao": timestamp,
        "versao_script": SCRIPT_VERSION,
        "registros": {},
    }

    arquivos_gerados = 0
    total_registros = 0
    erros = 0

    print(f"\nFocus Bulletin Tracker - Pipeline de dados")
    print(f"Timestamp  : {timestamp}")
    print(f"Indicadores: {list(INDICADORES.keys())}")
    print(f"Anos       : {ANOS[0]} a {ANOS[-1]}")
    print("-" * 56)

    for indicador in INDICADORES.keys():
        for ano in ANOS:
            chave = f"{indicador}/{ano}"
            try:
                df = _buscar_anual(indicador, ano)

                # Fallback para Câmbio quando o endpoint anual não tem dados
                if df.empty and indicador == "Câmbio":
                    logger.info("Fallback Top5 para Câmbio/%s", ano)
                    df = _buscar_cambio_top5(ano)

                n = len(df)
                if n > 0:
                    nome = f"{indicador.replace(' ', '_')}_{ano}.parquet"
                    df.to_parquet(PROCESSED_DIR / nome, index=False)
                    arquivos_gerados += 1
                    total_registros += n
                    metadata["registros"][chave] = n
                    print(f"  [OK]  {chave:<24}  {n:>4} registros")
                    logger.info("Salvo: %s - %d registros", chave, n)
                else:
                    print(f"  [--]  {chave:<24}  sem dados")
                    logger.debug("Sem dados: %s", chave)

            except Exception as e:
                print(f"  [ERR] {chave:<24}  {e}")
                logger.error("Erro ao buscar %s: %s", chave, e)
                erros += 1

            time.sleep(_DELAY)

    # Salva metadata.json
    meta_path = PROCESSED_DIR / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    elapsed = time.perf_counter() - inicio_total

    print("-" * 56)
    print(f"Arquivos gerados  : {arquivos_gerados}")
    print(f"Total de registros: {total_registros:,}")
    print(f"Erros             : {erros}")
    print(f"Tempo total       : {elapsed:.1f}s")
    print(f"Metadata          : {meta_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()

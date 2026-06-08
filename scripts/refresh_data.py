"""
Atualização incremental dos dados do Boletim Focus — Focus Bulletin Tracker.

Diferente de ``scripts/fetch_data.py`` (que SOBRESCREVE cada Parquet), este
script MESCLA os dados frescos da API Olinda do BCB com os Parquets já
existentes em ``data/processed/``, deduplicando por
``(Indicador, Data, DataReferencia)``. É o script usado pelo workflow semanal
``.github/workflows/weekly_data_refresh.yml``.

Reaproveita a lógica de fetch já existente no projeto:
  - ``scripts.fetch_data._buscar_anual``      → ExpectativasMercadoAnuais (sem cache)
  - ``scripts.fetch_data._buscar_cambio_top5``→ fallback Top5 para Câmbio
  - ``data.fetcher._salvar_cache``            → grava no mesmo SQLite do app
  - ``data.fetcher._parquet_path``            → mesmos caminhos de Parquet do app

Uso:
    python scripts/refresh_data.py             # busca, mescla e grava
    python scripts/refresh_data.py --dry-run   # não grava nada; só relata o que mudaria
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Adiciona a raiz do projeto ao sys.path ────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pandas as pd
import truststore

truststore.inject_into_ssl()

from data.fetcher import (
    INDICADORES,
    PROCESSED_DIR,
    _parquet_path,
    _salvar_cache,
)
from scripts.fetch_data import _buscar_anual, _buscar_cambio_top5
from utils.logger import get_logger

logger = get_logger("scripts.refresh_data")

SCRIPT_VERSION = "1.0.0"
ANOS = [str(ano) for ano in range(2022, 2030)]
_DELAY = 0.25  # segundos entre requisições — seja gentil com a API do BCB
_DEDUP_KEYS = ["Indicador", "Data", "DataReferencia"]


# ---------------------------------------------------------------------------
# Mesclagem incremental
# ---------------------------------------------------------------------------

def _ler_parquet_existente(indicador: str, ano: str):
    """Lê o Parquet já versionado para (indicador, ano), ou None se ausente."""
    path = _parquet_path(indicador, ano)
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        logger.warning("Falha ao ler Parquet existente %s: %s", path.name, e)
        return None


def _mesclar(df_existente, df_novo):
    """
    Concatena dados existentes + novos e remove duplicatas por
    (Indicador, Data, DataReferencia), mantendo a linha mais recente
    (``keep='last'`` → valores recém-buscados prevalecem).

    Retorna (df_mesclado, n_novas_linhas).
    """
    tem_existente = df_existente is not None and not df_existente.empty
    tem_novo = df_novo is not None and not df_novo.empty

    if not tem_existente and not tem_novo:
        return pd.DataFrame(), 0
    if not tem_existente:
        base = df_novo.copy()
    elif not tem_novo:
        base = df_existente.copy()
    else:
        base = pd.concat([df_existente, df_novo], ignore_index=True)

    n_antes = 0 if not tem_existente else len(df_existente)
    base = base.drop_duplicates(subset=_DEDUP_KEYS, keep="last")
    base = base.sort_values("Data").reset_index(drop=True)
    return base, len(base) - n_antes


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def main(dry_run: bool = False) -> int:
    inicio_total = time.perf_counter()
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not dry_run:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    modo = "DRY-RUN (nenhuma gravação)" if dry_run else "GRAVAÇÃO"
    print(f"\nFocus Bulletin Tracker - Atualização incremental [{modo}]")
    print(f"Timestamp  : {timestamp}")
    print(f"Indicadores: {list(INDICADORES.keys())}")
    print(f"Anos       : {ANOS[0]} a {ANOS[-1]}")
    print("-" * 64)

    metadata = {
        "ultima_atualizacao": timestamp,
        "versao_script": SCRIPT_VERSION,
        "registros": {},
    }

    arquivos_alterados = 0
    total_linhas_novas = 0
    erros = 0

    for indicador in INDICADORES.keys():
        for ano in ANOS:
            chave = f"{indicador}/{ano}"
            try:
                df_novo = _buscar_anual(indicador, ano)
                if df_novo.empty and indicador == "Câmbio":
                    logger.info("Fallback Top5 para Câmbio/%s", ano)
                    df_novo = _buscar_cambio_top5(ano)

                df_existente = _ler_parquet_existente(indicador, ano)
                df_mesclado, novas = _mesclar(df_existente, df_novo)

                n_total = len(df_mesclado)
                if n_total > 0:
                    metadata["registros"][chave] = n_total

                if novas > 0:
                    arquivos_alterados += 1
                    total_linhas_novas += novas
                    marcador = "[+]" if not dry_run else "[~]"
                    print(f"  {marcador}  {chave:<24}  +{novas:>4} novas  (total {n_total})")
                    if not dry_run:
                        df_mesclado.to_parquet(_parquet_path(indicador, ano), index=False)
                        _salvar_cache(df_mesclado, indicador, ano)
                        logger.info("Atualizado %s: +%d novas (total %d)", chave, novas, n_total)
                else:
                    print(f"  [=]  {chave:<24}  sem novidades  (total {n_total})")

            except Exception as e:
                print(f"  [ERR] {chave:<24}  {e}")
                logger.error("Erro ao atualizar %s: %s", chave, e)
                erros += 1

            time.sleep(_DELAY)

    # metadata.json — só grava fora do dry-run e quando houve alteração
    meta_path = PROCESSED_DIR / "metadata.json"
    if not dry_run and arquivos_alterados > 0:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    elapsed = time.perf_counter() - inicio_total

    print("-" * 64)
    print(f"Arquivos com novidades : {arquivos_alterados}")
    print(f"Linhas novas (total)   : {total_linhas_novas:,}")
    print(f"Erros                  : {erros}")
    print(f"Tempo total            : {elapsed:.1f}s")
    if dry_run:
        print("DRY-RUN: nenhum Parquet/SQLite/metadata foi gravado.")
    elif arquivos_alterados == 0:
        print("Sem mudanças nos dados — nada foi gravado.")
    else:
        print(f"Metadata atualizada    : {meta_path.relative_to(_ROOT)}")

    return 1 if erros else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Atualização incremental dos dados do Boletim Focus.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Busca e calcula o diff, mas não grava Parquet/SQLite/metadata.",
    )
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))

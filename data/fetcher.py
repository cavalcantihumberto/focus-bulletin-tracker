"""
Módulo de coleta de dados da API BCB Olinda.
Busca expectativas anuais de mercado com cache local em SQLite (validade: 24h).
"""

import json
import math
import sqlite3
import ssl
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import certifi
import pandas as pd
import requests
import truststore

from utils.logger import get_logger

# Injeta o armazenamento de certificados do sistema operacional no ssl padrão.
# Necessário para validar a cadeia ICP-Brasil usada pela API do BCB no Windows.
truststore.inject_into_ssl()

_SSL_VERIFY = True
logger = get_logger(__name__)

BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
ENDPOINT = "ExpectativasMercadoAnuais"
ENDPOINT_TOP5 = "ExpectativasMercadoTop5Anuais"

CAMPOS_TOP5 = [
    "Indicador",
    "Data",
    "DataReferencia",
    "Mediana",
    "Media",
    "DesvioPadrao",
    "Minimo",
    "Maximo",
]

CACHE_DIR = Path(__file__).parent.parent / "cache"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
CACHE_EXPIRY_HOURS = 24
PARQUET_MAX_AGE_DAYS = 7

INDICADORES = {
    "IPCA": "IPCA",
    "Selic": "Selic",
    "PIB Total": "PIB Total",
    "Câmbio": "Câmbio",
}

CAMPOS = [
    "Indicador",
    "Data",
    "DataReferencia",
    "baseCalculo",
    "Mediana",
    "Media",
    "DesvioPadrao",
    "Minimo",
    "Maximo",
]

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Infraestrutura SQLite
# ---------------------------------------------------------------------------

@contextmanager
def _db_conn():
    """Abre, inicializa e fecha uma conexão SQLite de forma segura."""
    db_path = CACHE_DIR / "focus_cache.db"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        _criar_tabelas(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _criar_tabelas(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expectativas (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            indicador       TEXT    NOT NULL,
            ano_referencia  TEXT    NOT NULL,
            data_coleta     TEXT    NOT NULL,
            data_registro   TEXT    NOT NULL,
            payload         TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exp_ind_ano
        ON expectativas (indicador, ano_referencia)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache_metadata (
            indicador          TEXT    NOT NULL,
            ano_referencia     TEXT    NOT NULL,
            ultima_atualizacao TEXT    NOT NULL,
            total_registros    INTEGER NOT NULL,
            PRIMARY KEY (indicador, ano_referencia)
        )
    """)


def _cache_valido(indicador: str, ano_referencia: str) -> bool:
    with _db_conn() as conn:
        row = conn.execute(
            "SELECT ultima_atualizacao FROM cache_metadata "
            "WHERE indicador=? AND ano_referencia=?",
            (indicador, ano_referencia),
        ).fetchone()
    if row is None:
        return False
    ultima = datetime.fromisoformat(row[0])
    return datetime.now() - ultima < timedelta(hours=CACHE_EXPIRY_HOURS)


def _ler_cache(indicador: str, ano_referencia: str) -> pd.DataFrame:
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT payload FROM expectativas "
            "WHERE indicador=? AND ano_referencia=? ORDER BY data_coleta",
            (indicador, ano_referencia),
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=CAMPOS)
    registros = [json.loads(r[0]) for r in rows]
    return _limpar_dataframe(pd.DataFrame(registros))


def _salvar_cache(df: pd.DataFrame, indicador: str, ano_referencia: str) -> None:
    agora = datetime.now().isoformat()
    with _lock:
        with _db_conn() as conn:
            conn.execute(
                "DELETE FROM expectativas WHERE indicador=? AND ano_referencia=?",
                (indicador, ano_referencia),
            )
            for _, row in df.iterrows():
                payload = _serializar_linha(row)
                conn.execute(
                    "INSERT INTO expectativas "
                    "(indicador, ano_referencia, data_coleta, data_registro, payload) "
                    "VALUES (?,?,?,?,?)",
                    (
                        indicador,
                        ano_referencia,
                        payload.get("Data", ""),
                        agora,
                        json.dumps(payload),
                    ),
                )
            conn.execute(
                "INSERT OR REPLACE INTO cache_metadata "
                "(indicador, ano_referencia, ultima_atualizacao, total_registros) "
                "VALUES (?,?,?,?)",
                (indicador, ano_referencia, agora, len(df)),
            )


def _parquet_path(indicador: str, ano_referencia: str) -> Path:
    return PROCESSED_DIR / f"{indicador.replace(' ', '_')}_{ano_referencia}.parquet"


def _tentar_ler_parquet(indicador: str, ano_referencia: str):
    """
    Tenta ler o Parquet pré-gerado pelo pipeline. Retorna None se:
    - O arquivo não existe
    - O arquivo tem mais de PARQUET_MAX_AGE_DAYS dias
    - Ocorre qualquer erro de leitura (fallback automático)
    """
    path = _parquet_path(indicador, ano_referencia)
    if not path.exists():
        return None
    modificado = datetime.fromtimestamp(path.stat().st_mtime)
    if datetime.now() - modificado >= timedelta(days=PARQUET_MAX_AGE_DAYS):
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        logger.warning("Falha ao ler Parquet %s: %s — usando fallback", path.name, e)
        return None


def _serializar_linha(row: pd.Series) -> dict:
    d = {}
    for col, val in row.items():
        if isinstance(val, pd.Timestamp):
            d[col] = val.strftime("%Y-%m-%d")
        elif isinstance(val, float) and math.isnan(val):
            d[col] = None
        elif hasattr(val, "item"):
            d[col] = val.item()
        else:
            d[col] = val
    return d


# ---------------------------------------------------------------------------
# Coleta da API
# ---------------------------------------------------------------------------

def buscar_expectativas(
    indicador: str,
    ano_referencia: str,
    forcar_atualizacao: bool = False,
) -> pd.DataFrame:
    """
    Busca as expectativas de mercado anuais para um indicador e ano de referência.

    Parâmetros:
        indicador        : Nome do indicador (ex: 'IPCA', 'Selic', 'PIB Total', 'Câmbio')
        ano_referencia   : Ano-alvo das projeções (ex: '2025')
        forcar_atualizacao: Se True, ignora o cache e consulta a API diretamente

    Lança:
        RuntimeError com mensagem amigável em caso de falha na API
    """
    logger.info(
        "Iniciando busca: %s/%s [%s]",
        indicador, ano_referencia,
        "forçado" if forcar_atualizacao else "com cache",
    )

    if not forcar_atualizacao:
        # Prioridade 1 — Parquet pré-gerado pelo pipeline (< 7 dias)
        df_parquet = _tentar_ler_parquet(indicador, ano_referencia)
        if df_parquet is not None:
            logger.info(
                "Parquet hit: %s/%s — %d registros [fonte: parquet]",
                indicador, ano_referencia, len(df_parquet),
            )
            return df_parquet

        # Prioridade 2 — SQLite (cache de 24h)
        if _cache_valido(indicador, ano_referencia):
            df = _ler_cache(indicador, ano_referencia)
            logger.info(
                "Cache hit: %s/%s — %d registros [fonte: sqlite]",
                indicador, ano_referencia, len(df),
            )
            return df

        logger.warning("Cache expirado ou ausente: %s/%s — buscando da API", indicador, ano_referencia)

    filtro = f"Indicador eq '{indicador}' and DataReferencia eq '{ano_referencia}'"
    qs = (
        f"$filter={quote(filtro)}"
        f"&$select={quote(','.join(CAMPOS))}"
        f"&$format=json"
        f"&$top=10000"
    )
    url = BASE_URL + ENDPOINT + "?" + qs

    inicio = time.perf_counter()
    try:
        resposta = requests.get(url, timeout=30, verify=_SSL_VERIFY)
        resposta.raise_for_status()
        dados = resposta.json()
    except requests.exceptions.SSLError:
        raise RuntimeError(
            "Falha na verificação do certificado SSL da API do Banco Central. "
            "Tente executar: pip install --upgrade certifi"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            "Tempo limite excedido ao conectar com a API do Banco Central. "
            "Tente novamente em alguns instantes."
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "Não foi possível conectar com a API do Banco Central. "
            "Verifique sua conexão com a internet."
        )
    except requests.exceptions.HTTPError as e:
        logger.error("Erro HTTP %s ao acessar %s", resposta.status_code, url)
        raise RuntimeError(f"Erro HTTP ao acessar a API BCB: {e}")
    except ValueError:
        raise RuntimeError(
            "A API retornou uma resposta inválida (JSON malformado). "
            "Tente novamente mais tarde."
        )
    except Exception as e:
        raise RuntimeError(f"Erro inesperado ao acessar a API: {e}")

    elapsed = time.perf_counter() - inicio
    registros = dados.get("value", [])

    logger.info(
        "API: %s/%s — %d registros em %.2fs",
        indicador, ano_referencia, len(registros), elapsed,
    )

    if not registros:
        if indicador == "Câmbio":
            return _buscar_cambio_top5(ano_referencia, forcar_atualizacao)
        return pd.DataFrame(columns=CAMPOS)

    df = pd.DataFrame(registros)

    if "baseCalculo" not in df.columns:
        logger.warning(
            "Coluna baseCalculo ausente no retorno da API para %s/%s",
            indicador, ano_referencia,
        )

    df = _limpar_dataframe(df)

    try:
        _salvar_cache(df, indicador, ano_referencia)
    except Exception as e:
        logger.error("Falha ao salvar cache para %s/%s: %s", indicador, ano_referencia, e)

    return df


def _limpar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Limpa, tipifica e ordena o DataFrame retornado pela API."""
    df["Data"] = pd.to_datetime(df["Data"], format="%Y-%m-%d", errors="coerce")

    for col in ["Mediana", "Media", "DesvioPadrao", "Minimo", "Maximo"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "baseCalculo" in df.columns:
        df["baseCalculo"] = pd.to_numeric(df["baseCalculo"], errors="coerce")
        df = df[df["baseCalculo"] == 0]

    df = df.dropna(subset=["Data"])
    df = df.sort_values("Data").reset_index(drop=True)
    df["Indicador"] = df["Indicador"].astype(str)
    df["DataReferencia"] = df["DataReferencia"].astype(str)
    return df


def _buscar_cambio_top5(ano_referencia: str, forcar_atualizacao: bool = False) -> pd.DataFrame:
    """
    Busca projeções anuais de Câmbio via ExpectativasMercadoTop5Anuais.
    Fallback quando ExpectativasMercadoAnuais não tem dados para o ano.
    """
    _KEY = "Câmbio_top5"

    logger.info("Iniciando busca Top5: Câmbio/%s [%s]", ano_referencia,
                "forçado" if forcar_atualizacao else "com cache")

    if not forcar_atualizacao and _cache_valido(_KEY, ano_referencia):
        df = _ler_cache(_KEY, ano_referencia)
        logger.info("Cache hit (Top5): Câmbio/%s — %d registros", ano_referencia, len(df))
        return df

    if not forcar_atualizacao:
        logger.warning("Cache expirado ou ausente (Top5): Câmbio/%s", ano_referencia)

    filtro = (
        f"Indicador eq 'Câmbio' and DataReferencia eq '{ano_referencia}'"
        f" and tipoCalculo eq 'M'"
    )
    qs = (
        f"$filter={quote(filtro)}"
        f"&$select={quote(','.join(CAMPOS_TOP5))}"
        f"&$format=json"
        f"&$top=10000"
    )
    url = BASE_URL + ENDPOINT_TOP5 + "?" + qs

    inicio = time.perf_counter()
    try:
        resposta = requests.get(url, timeout=30, verify=_SSL_VERIFY)
        resposta.raise_for_status()
        dados = resposta.json()
    except requests.exceptions.SSLError:
        raise RuntimeError("Falha na verificação do certificado SSL da API do Banco Central.")
    except requests.exceptions.Timeout:
        raise RuntimeError("Tempo limite excedido ao conectar com a API do Banco Central.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Não foi possível conectar com a API do Banco Central.")
    except requests.exceptions.HTTPError as e:
        logger.error("Erro HTTP %s ao acessar %s (Top5)", resposta.status_code, url)
        raise RuntimeError(f"Erro HTTP ao acessar a API BCB (Top5): {e}")
    except Exception as e:
        raise RuntimeError(f"Erro inesperado ao acessar a API (Top5): {e}")

    elapsed = time.perf_counter() - inicio
    registros = dados.get("value", [])

    logger.info("API Top5: Câmbio/%s — %d registros em %.2fs", ano_referencia, len(registros), elapsed)

    if not registros:
        return pd.DataFrame(columns=CAMPOS_TOP5)

    df = pd.DataFrame(registros)
    df = _limpar_dataframe(df)

    try:
        _salvar_cache(df, _KEY, ano_referencia)
    except Exception as e:
        logger.error("Falha ao salvar cache Top5 para Câmbio/%s: %s", ano_referencia, e)

    return df


def buscar_valores_realizados(indicador: str) -> pd.DataFrame:
    """
    Busca valores anuais realizados para IPCA (BCB série 13522),
    Selic (BCB série 1178) ou PIB Total (IBGE agregado 1621).

    Retorna DataFrame com colunas: ano (int), valor_realizado (float), fonte (str).
    Filtra apenas anos completos (exclui ano corrente e futuros).
    Em caso de falha na API retorna DataFrame vazio.
    """
    ano_atual = datetime.now().year
    _EMPTY = pd.DataFrame(columns=["ano", "valor_realizado", "fonte"])

    def _parse_bcb_dezembro(url: str, fonte: str) -> pd.DataFrame:
        """Busca série BCB diária/mensal e retorna o último valor de dezembro de cada ano."""
        resp = requests.get(url, timeout=30, verify=_SSL_VERIFY)
        resp.raise_for_status()
        por_ano: dict = {}
        for item in resp.json():
            try:
                data = datetime.strptime(item["data"], "%d/%m/%Y")
                valor = float(item["valor"])
            except (ValueError, KeyError, TypeError):
                continue
            if data.month != 12 or data.year >= ano_atual:
                continue
            if data.year not in por_ano or data > por_ano[data.year][0]:
                por_ano[data.year] = (data, valor)
        registros = [
            {"ano": ano, "valor_realizado": v, "fonte": fonte}
            for ano, (_, v) in sorted(por_ano.items())
        ]
        return pd.DataFrame(registros) if registros else _EMPTY

    def _parse_bcb_anual(url: str, fonte: str) -> pd.DataFrame:
        """Busca série BCB de frequência anual (data = 01/01/YYYY)."""
        resp = requests.get(url, timeout=30, verify=_SSL_VERIFY)
        resp.raise_for_status()
        registros = []
        for item in resp.json():
            try:
                ano = datetime.strptime(item["data"], "%d/%m/%Y").year
                valor = float(item["valor"])
            except (ValueError, KeyError, TypeError):
                continue
            if ano >= ano_atual:
                continue
            registros.append({"ano": ano, "valor_realizado": valor, "fonte": fonte})
        return pd.DataFrame(registros) if registros else _EMPTY

    try:
        if indicador == "IPCA":
            # Série 13522: IPCA acumulado no ano — frequência mensal, filtrar dezembro
            url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados?formato=json"
            return _parse_bcb_dezembro(url, "BCB SGS 13522")

        elif indicador == "Selic":
            # Série 432: meta Selic % a.a. — frequência diária, janela de 6 anos
            # (9 anos excede o tempo de resposta aceitável para série diária)
            data_ini = f"01/01/{ano_atual - 6}"
            data_fim = f"31/12/{ano_atual - 1}"
            url = (
                "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados"
                f"?formato=json&dataInicial={data_ini}&dataFinal={data_fim}"
            )
            return _parse_bcb_dezembro(url, "BCB SGS 432")

        elif indicador in ("PIB Total", "PIB"):
            # Série 7326: variação anual real do PIB (frequência anual, data = 01/01/YYYY)
            data_ini = f"01/01/{ano_atual - 9}"
            data_fim = f"31/12/{ano_atual - 1}"
            url = (
                "https://api.bcb.gov.br/dados/serie/bcdata.sgs.7326/dados"
                f"?formato=json&dataInicial={data_ini}&dataFinal={data_fim}"
            )
            return _parse_bcb_anual(url, "BCB SGS 7326")

        else:
            logger.warning("buscar_valores_realizados: indicador '%s' não suportado", indicador)
            return _EMPTY

    except Exception as e:
        logger.warning("Falha ao buscar valores realizados para %s: %s", indicador, e)
        return _EMPTY


def buscar_multiplos_anos(
    indicador: str,
    anos: list,
    forcar_atualizacao: bool = False,
) -> pd.DataFrame:
    """Busca dados para vários anos e concatena em um único DataFrame."""
    frames = []
    for ano in anos:
        try:
            df = buscar_expectativas(indicador, ano, forcar_atualizacao)
            if not df.empty:
                frames.append(df)
        except RuntimeError:
            continue

    if not frames:
        return pd.DataFrame(columns=CAMPOS)

    return pd.concat(frames, ignore_index=True)


def limpar_cache_disco(indicador: str, ano_referencia: str) -> None:
    """
    Remove registros de cache do SQLite para indicador+ano.
    Também apaga arquivos CSV legados, caso ainda existam da versão anterior.
    """
    chaves = [indicador, indicador + "_top5"]
    with _lock:
        with _db_conn() as conn:
            for chave in chaves:
                conn.execute(
                    "DELETE FROM expectativas WHERE indicador=? AND ano_referencia=?",
                    (chave, ano_referencia),
                )
                conn.execute(
                    "DELETE FROM cache_metadata WHERE indicador=? AND ano_referencia=?",
                    (chave, ano_referencia),
                )

    for chave in chaves:
        csv_legado = CACHE_DIR / f"{chave.replace(' ', '_')}_{ano_referencia}.csv"
        if csv_legado.exists():
            csv_legado.unlink()


def anos_disponiveis() -> list:
    """Retorna os anos disponíveis para seleção: últimos 4 anos até 3 anos à frente."""
    ano_atual = datetime.now().year
    return [str(ano) for ano in range(ano_atual - 4, ano_atual + 4)]

"""
Módulo de coleta de dados da API BCB Olinda.
Busca expectativas anuais de mercado com cache local em SQLite (validade: 24h).
"""

import json
import math
import sqlite3
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import certifi
import pandas as pd
import requests
import truststore

# Injeta o armazenamento de certificados do sistema operacional no ssl padrão.
# Necessário para validar a cadeia ICP-Brasil usada pela API do BCB no Windows.
truststore.inject_into_ssl()

_SSL_VERIFY = True

BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
ENDPOINT = "ExpectativasMercadoAnuais"

# Fallback para Câmbio 2028+
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
CACHE_EXPIRY_HOURS = 24

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

# Lock global para serializar escritas concorrentes no banco SQLite
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
    # WAL permite leituras simultâneas durante uma escrita
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
    """Cria as tabelas e índice caso ainda não existam (idempotente)."""
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
    """Retorna True se existe cache SQLite com menos de 24h para indicador+ano."""
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
    """Reconstrói o DataFrame a partir dos payloads JSON armazenados no SQLite."""
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
    """Persiste o DataFrame no SQLite e atualiza cache_metadata."""
    agora = datetime.now().isoformat()
    with _lock:
        with _db_conn() as conn:
            # Substitui registros anteriores do mesmo indicador+ano
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


def _serializar_linha(row: pd.Series) -> dict:
    """Converte uma linha do DataFrame em dicionário JSON-serializável."""
    d = {}
    for col, val in row.items():
        if isinstance(val, pd.Timestamp):
            d[col] = val.strftime("%Y-%m-%d")
        elif isinstance(val, float) and math.isnan(val):
            d[col] = None
        elif hasattr(val, "item"):  # numpy scalar → Python nativo
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

    Retorna:
        DataFrame com colunas: Indicador, Data, DataReferencia, Mediana, Media,
                                DesvioPadrao, Minimo, Maximo

    Lança:
        RuntimeError com mensagem amigável em caso de falha na API
    """
    if not forcar_atualizacao and _cache_valido(indicador, ano_referencia):
        return _ler_cache(indicador, ano_referencia)

    # Monta URL com query string OData manualmente — o requests codificaria os '$' como '%24',
    # o que faz a API BCB retornar 400. Construir a string diretamente preserva os literais.
    filtro = f"Indicador eq '{indicador}' and DataReferencia eq '{ano_referencia}'"
    qs = (
        f"$filter={quote(filtro)}"
        f"&$select={quote(','.join(CAMPOS))}"
        f"&$format=json"
        f"&$top=10000"
    )
    url = BASE_URL + ENDPOINT + "?" + qs

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
        raise RuntimeError(f"Erro HTTP ao acessar a API BCB: {e}")
    except ValueError:
        raise RuntimeError(
            "A API retornou uma resposta inválida (JSON malformado). "
            "Tente novamente mais tarde."
        )
    except Exception as e:
        raise RuntimeError(f"Erro inesperado ao acessar a API: {e}")

    registros = dados.get("value", [])

    if not registros:
        if indicador == "Câmbio":
            return _buscar_cambio_top5(ano_referencia, forcar_atualizacao)
        return pd.DataFrame(columns=CAMPOS)

    df = pd.DataFrame(registros)
    df = _limpar_dataframe(df)
    _salvar_cache(df, indicador, ano_referencia)
    return df


def _limpar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Limpa, tipifica e ordena o DataFrame retornado pela API."""
    df["Data"] = pd.to_datetime(df["Data"], format="%Y-%m-%d", errors="coerce")

    for col in ["Mediana", "Media", "DesvioPadrao", "Minimo", "Maximo"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Mantém apenas registros sem suavização (baseCalculo == 0 → dado padrão do Focus).
    # A coluna pode estar ausente em endpoints alternativos (Top5Anuais).
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

    Usado como fallback quando ExpectativasMercadoAnuais não tem dados para o ano
    solicitado. Filtra tipoCalculo='M' para evitar duplicatas.
    """
    _KEY = "Câmbio_top5"

    if not forcar_atualizacao and _cache_valido(_KEY, ano_referencia):
        return _ler_cache(_KEY, ano_referencia)

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
        raise RuntimeError(f"Erro HTTP ao acessar a API BCB (Top5): {e}")
    except Exception as e:
        raise RuntimeError(f"Erro inesperado ao acessar a API (Top5): {e}")

    registros = dados.get("value", [])
    if not registros:
        return pd.DataFrame(columns=CAMPOS_TOP5)

    df = pd.DataFrame(registros)
    df = _limpar_dataframe(df)
    _salvar_cache(df, _KEY, ano_referencia)
    return df


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

    # Limpa CSVs gerados pela versão anterior do cache (migração)
    for chave in chaves:
        csv_legado = CACHE_DIR / f"{chave.replace(' ', '_')}_{ano_referencia}.csv"
        if csv_legado.exists():
            csv_legado.unlink()


def anos_disponiveis() -> list:
    """Retorna os anos disponíveis para seleção: últimos 4 anos até 3 anos à frente."""
    ano_atual = datetime.now().year
    return [str(ano) for ano in range(ano_atual - 4, ano_atual + 4)]

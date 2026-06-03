"""
Módulo de coleta de dados da API BCB Olinda.
Busca expectativas anuais de mercado com cache local em CSV (validade: 24h).
"""

import ssl
import certifi
import truststore
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# Injeta o armazenamento de certificados do sistema operacional no ssl padrão.
# Necessário para validar a cadeia ICP-Brasil usada pela API do BCB no Windows.
truststore.inject_into_ssl()

_SSL_VERIFY = True  # usa o contexto SSL já corrigido pelo truststore

# URL base da API BCB Olinda
BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
ENDPOINT = "ExpectativasMercadoAnuais"

# Fallback para Câmbio 2028+: o endpoint anual não coleta câmbio para anos tão
# distantes, mas o Top5Anuais (5 melhores instituições) tem esses dados anuais.
ENDPOINT_TOP5 = "ExpectativasMercadoTop5Anuais"

# Campos do Top5Anuais — sem baseCalculo (não existe nesse endpoint)
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

# Diretório de cache (relativo à raiz do projeto)
CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_EXPIRY_HOURS = 24

# Indicadores disponíveis no Boletim Focus
INDICADORES = {
    "IPCA": "IPCA",
    "Selic": "Selic",
    "PIB Total": "PIB Total",
    "Câmbio": "Câmbio",
}

# Campos solicitados à API via OData $select
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


def _cache_path(indicador: str, ano_referencia: str) -> Path:
    """Retorna o caminho do arquivo CSV de cache para um indicador/ano."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    nome = f"{indicador.replace(' ', '_')}_{ano_referencia}.csv"
    return CACHE_DIR / nome


def _cache_valido(path: Path) -> bool:
    """Verifica se o arquivo de cache existe e ainda está dentro do prazo de validade."""
    if not path.exists():
        return False
    modificado = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - modificado < timedelta(hours=CACHE_EXPIRY_HOURS)


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
    cache_path = _cache_path(indicador, ano_referencia)

    # Usa cache se válido e não forçou atualização.
    # Reaplica _limpar_dataframe para que filtros adicionados depois da gravação
    # do CSV (ex.: baseCalculo == 0) sejam sempre respeitados.
    if not forcar_atualizacao and _cache_valido(cache_path):
        df = pd.read_csv(cache_path, parse_dates=["Data"])
        return _limpar_dataframe(df)

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
        # ExpectativasMercadoAnuais não tem Câmbio para anos distantes (2028+).
        # Tenta o fallback via Top5Anuais antes de desistir.
        if indicador == "Câmbio":
            return _buscar_cambio_top5(ano_referencia, forcar_atualizacao)
        return pd.DataFrame(columns=CAMPOS)

    df = pd.DataFrame(registros)
    df = _limpar_dataframe(df)

    # Persiste no cache
    df.to_csv(cache_path, index=False)

    return df


def _limpar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Limpa, tipifica e ordena o DataFrame retornado pela API."""
    # Converte data
    df["Data"] = pd.to_datetime(df["Data"], format="%Y-%m-%d", errors="coerce")

    # Converte colunas numéricas (a API pode retornar strings)
    colunas_numericas = ["Mediana", "Media", "DesvioPadrao", "Minimo", "Maximo"]
    for col in colunas_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Mantém apenas registros sem suavização (baseCalculo == 0 → dado padrão do Focus).
    # A coluna pode estar ausente em respostas antigas de cache ou em endpoints alternativos.
    if "baseCalculo" in df.columns:
        df["baseCalculo"] = pd.to_numeric(df["baseCalculo"], errors="coerce")
        df = df[df["baseCalculo"] == 0]

    # Remove linhas sem data válida
    df = df.dropna(subset=["Data"])

    # Ordena por data crescente e reseta índice
    df = df.sort_values("Data").reset_index(drop=True)

    # Garante tipo string nas colunas textuais
    df["Indicador"] = df["Indicador"].astype(str)
    df["DataReferencia"] = df["DataReferencia"].astype(str)

    return df


def _buscar_cambio_top5(ano_referencia: str, forcar_atualizacao: bool = False) -> pd.DataFrame:
    """
    Busca projeções anuais de Câmbio via ExpectativasMercadoTop5Anuais.

    Usado como fallback quando ExpectativasMercadoAnuais não tem dados para o ano
    solicitado (tipicamente 2028 em diante). O Top5Anuais representa as 5
    instituições com melhor histórico de previsão, não o consenso pleno de ~130
    participantes — os valores podem divergir ligeiramente do Boletim Focus oficial.

    Filtra tipoCalculo='M' (média ponderada das top 5) para evitar duplicatas,
    já que o endpoint retorna dois registros por data ('M' e 'L').
    """
    cache_path = _cache_path("Câmbio_top5", ano_referencia)

    if not forcar_atualizacao and _cache_valido(cache_path):
        df = pd.read_csv(cache_path, parse_dates=["Data"])
        return _limpar_dataframe(df)

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
        raise RuntimeError(
            "Falha na verificação do certificado SSL da API do Banco Central."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            "Tempo limite excedido ao conectar com a API do Banco Central."
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "Não foi possível conectar com a API do Banco Central."
        )
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Erro HTTP ao acessar a API BCB (Top5): {e}")
    except Exception as e:
        raise RuntimeError(f"Erro inesperado ao acessar a API (Top5): {e}")

    registros = dados.get("value", [])
    if not registros:
        return pd.DataFrame(columns=CAMPOS_TOP5)

    df = pd.DataFrame(registros)
    df = _limpar_dataframe(df)
    df.to_csv(cache_path, index=False)
    return df


def buscar_multiplos_anos(
    indicador: str,
    anos: list,
    forcar_atualizacao: bool = False,
) -> pd.DataFrame:
    """
    Busca dados para vários anos e concatena em um único DataFrame.
    Anos sem dados são silenciosamente ignorados.
    """
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
    """Remove os arquivos CSV de cache para um indicador/ano (inclui o cache Top5)."""
    for path in [
        _cache_path(indicador, ano_referencia),
        _cache_path(indicador + "_top5", ano_referencia),
    ]:
        if path.exists():
            path.unlink()


def anos_disponiveis() -> list:
    """Retorna os anos disponíveis para seleção: últimos 4 anos até 3 anos à frente.

    O Focus coleta projeções para até ~3 anos no futuro (confirmado: Câmbio 2028/2029
    já disponível na API em 2026), portanto o horizonte vai até ano_atual + 3.
    """
    ano_atual = datetime.now().year
    return [str(ano) for ano in range(ano_atual - 4, ano_atual + 4)]

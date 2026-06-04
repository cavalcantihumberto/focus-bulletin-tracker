import sys
sys.path.insert(0, ".")
import truststore
truststore.inject_into_ssl()
from data.fetcher import buscar_valores_realizados

for ind in ["IPCA", "Selic", "PIB Total"]:
    df = buscar_valores_realizados(ind)
    if df.empty:
        print(f"[ERR] {ind}: DataFrame vazio")
    else:
        fonte = df["fonte"].iloc[0]
        anos = sorted(df["ano"].tolist())
        print(f"[OK]  {ind:<10} {len(df):>2} anos  ({anos[0]}-{anos[-1]})  fonte: {fonte}")
        for _, r in df.tail(4).iterrows():
            print(f"       {int(r['ano'])}: {r['valor_realizado']:.2f}")

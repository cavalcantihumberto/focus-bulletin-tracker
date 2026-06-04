"""
Focus Bulletin Tracker
Dashboard interativo para análise das expectativas do Boletim Focus — BCB
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

from data.fetcher import (
    buscar_expectativas,
    buscar_multiplos_anos,
    buscar_valores_realizados,
    limpar_cache_disco,
    INDICADORES,
    anos_disponiveis,
)
from analysis.metrics import (
    calcular_pipeline_completo,
    calcular_erro_consenso,
    resumo_estatistico,
    ultimas_semanas,
)
from utils.logger import get_logger

logger = get_logger(__name__)


@st.cache_data(ttl=86400, show_spinner=False)
def _buscar_dados(indicador: str, ano_ref: str) -> pd.DataFrame:
    return buscar_expectativas(indicador, ano_ref)


@st.cache_data(ttl=86400, show_spinner=False)
def _buscar_todos_anos(indicador: str) -> pd.DataFrame:
    ano_atual = datetime.now().year
    anos = [str(a) for a in range(2022, ano_atual)]
    return buscar_multiplos_anos(indicador, anos)


@st.cache_data(ttl=86400 * 7, show_spinner=False)
def _buscar_realizados(indicador: str) -> pd.DataFrame:
    return buscar_valores_realizados(indicador)


def get_erro_consenso_content(indicador: str) -> str:
    ind = "PIB" if indicador.startswith("PIB") else indicador
    conteudo = {
        "IPCA": """
**O que mostra:** compara o que o mercado projetava com o IPCA que efetivamente ocorreu. Erro positivo = mercado projetou inflação maior do que foi. Erro negativo = mercado subestimou a inflação.

💼 **Assessores e CFP®:** se o erro histórico médio é negativo (mercado sistematicamente subestima o IPCA), isso sugere que projeções do Focus tendem a ser otimistas — considere um prêmio de segurança ao recomendar IPCA+ para clientes conservadores.

📊 **Gestores de RPPS:** o erro absoluto médio é sua margem de incerteza histórica. Se a média é 1,5 pp, sua meta atuarial precisa de pelo menos essa folga em relação ao IPCA projetado para ser robusta a erros do consenso.

🏦 **Economistas:** analise se o erro diminui conforme o horizonte encurta — se não diminui, o mercado não está incorporando informação nova de forma eficiente.

🏢 **Empresas:** use o erro histórico para ajustar o orçamento de contratos IPCA+ — se o mercado subestima sistematicamente, adicione o erro médio histórico como buffer no seu planejamento.

👤 **Pessoa Física:** se o mercado historicamente subestima o IPCA, o Tesouro IPCA+ protege melhor do que o Prefixado mesmo quando as taxas parecem equivalentes.
""",
        "Selic": """
**O que mostra:** compara a Selic projetada pelo Focus com a Selic meta efetivamente definida pelo Copom ao final de cada ano.

💼 **Assessores e CFP®:** erro positivo (mercado projetou Selic mais alta do que foi) significa que o mercado foi hawkish demais — quem travou prefixados quando o consenso estava pessimista ganhou. Use o histórico de erros para identificar esses momentos.

📊 **Gestores de RPPS:** a Selic realizada vs projetada define o retorno efetivo da parcela pós-fixada vs o que você planejou. Erros sistemáticos impactam diretamente o ALM — ajuste as premissas de retorno esperado com base no erro histórico médio.

🏦 **Economistas:** compare o erro da Selic com o erro do IPCA no mesmo ano. Se o mercado errou o IPCA mas acertou a Selic, o Copom foi mais previsível do que a inflação — ou vice-versa.

🏢 **Empresas:** erro positivo na Selic (juros vieram menores) significa que o custo de dívida CDI foi menor do que o planejado — oportunidade de revisão de hedge retroativa para entender se o timing foi correto.

👤 **Pessoa Física:** se o mercado historicamente projeta Selic mais alta do que realiza, isso significa que travar prefixados quando o Focus está pessimista tende a ser uma boa estratégia.
""",
        "PIB": """
**O que mostra:** compara o crescimento do PIB projetado com o crescimento efetivo divulgado pelo IBGE.

💼 **Assessores e CFP®:** erro negativo sistemático (mercado subestima o PIB) sugere que o Brasil cresce mais do que o esperado — contexto favorável para ativos de risco quando o consenso está pessimista.

📊 **Gestores de RPPS:** PIB realizado acima do projetado geralmente significa arrecadação maior e contribuições mais estáveis — use o histórico de erros para calibrar o cenário conservador do fluxo de caixa do fundo.

🏦 **Economistas:** analise a correlação entre erro do PIB e erro do IPCA — crescimento acima do esperado sem inflação acima do esperado indica ganhos de produtividade, o cenário mais favorável para política monetária.

🏢 **Empresas:** erro negativo no PIB (economia cresceu mais do que o mercado esperava) valida estratégias de expansão mesmo quando o consenso era pessimista. Use o histórico para calibrar o quanto confiar nas projeções de mercado no planejamento estratégico.

👤 **Pessoa Física:** mercado sistematicamente pessimista com o PIB significa que momentos de consenso negativo sobre a economia podem ser oportunidades de entrada em ativos de risco.
""",
    }
    return conteudo.get(ind, "_Conteúdo não disponível para este indicador._")


def get_expander_content(indicador: str, grafico: str) -> str:
    """
    Retorna o markdown explicativo para cada combinação de indicador × seção.

    Parâmetros:
        indicador : "IPCA", "Selic", "PIB Total" ou "Câmbio"
        grafico   : "mediana", "dispersao", "revisoes" ou "tabela"
    """
    # Normaliza "PIB Total" → "PIB" para simplificar o mapeamento
    ind = "PIB" if indicador.startswith("PIB") else indicador

    conteudo = {
        ("IPCA", "mediana"): """
**O que este gráfico mostra:**
A trajetória semanal do consenso de mercado para a inflação oficial do Brasil no ano selecionado. Cada ponto representa a mediana das projeções de ~130 instituições financeiras. As estrelinhas marcam semanas com revisão acima do threshold configurado.

**Como usar — por perfil:**

💼 **Assessores de Investimento e CFP®**
Acompanhe a direção da mediana antes de recomendar entre prefixado e IPCA+. Mediana em trajetória de alta consistente favorece IPCA+. Exemplo prático: a mediana do IPCA 2026 saiu de 3% em jan/2022 e chegou a 5,09% em mai/2026 — clientes com Tesouro Prefixado longo travado no início desse ciclo perderam retorno real significativo em relação ao IPCA+.

📊 **Gestores de RPPS**
Compare a mediana projetada com sua meta atuarial (tipicamente IPCA + 5,5% ou 6%). Se o IPCA projetado é 5,09% e a meta é IPCA+5,5%, o retorno real mínimo necessário é 0,41% — esse número define o piso de taxa dos ativos que você deve buscar no mercado. Monitore semanalmente para ajustar o ALM conforme o cenário evolui.

🏦 **Economistas e Analistas de Mercado**
Use o histórico para identificar padrões de revisão por ciclo econômico. Compare os momentos de estrelinha (revisão relevante) com datas de reunião do Copom, divulgações de IPCA-15 e eventos fiscais para calibrar modelos e identificar se o mercado está sistematicamente otimista ou pessimista em determinados períodos.

🏢 **Empresas e Tesourarias Corporativas**
Contratos indexados ao IPCA (aluguéis, debêntures, fornecedores) terão custo crescente se a mediana está em alta consistente. Negocie contratos prefixados ou acione hedge quando a mediana estiver em trajetória de alta. Prefira renovar contratos indexados após períodos de revisão para baixo.

👤 **Investidor Pessoa Física**
Mediana acima de 4,5% é argumento concreto para preferir Tesouro IPCA+ ao Tesouro Prefixado na próxima aplicação — você protege o poder de compra independente de onde a inflação for parar.
""",
        ("IPCA", "dispersao"): """
**O que este gráfico mostra:**
A banda entre a projeção mínima e máxima de todas as instituições participantes do Focus. Quanto maior a área azul, maior a divergência de opiniões — e portanto maior a incerteza do mercado. A linha central é a mediana; as linhas tracejadas são ±1 desvio padrão.

**Como usar — por perfil:**

💼 **Assessores de Investimento e CFP®**
Banda acima de 3 pp indica momento de evitar travar posições longas. Exemplo: em jul/2023 a amplitude chegou a 6 pp — um assessor que travou taxa longa naquele momento assumiu risco de cenário muito elevado. Prefira vencimentos curtos ou diversificação até o mercado convergir.

📊 **Gestores de RPPS**
Dispersão alta exige conservadorismo nas premissas do ALM. Quando a banda está larga, a precificação dos ativos IPCA+ pode variar muito entre diferentes casas — seja conservador e evite concentração em vencimentos longos nesses períodos.

🏦 **Economistas e Analistas de Mercado**
Dispersão crescente com mediana estável é sinal de risco latente — o consenso central não mudou, mas o mercado está cada vez mais dividido. É um indicador antecedente de volatilidade que a mediana sozinha não captura.

🏢 **Empresas e Tesourarias Corporativas**
A amplitude entre mínimo e máximo representa a margem de incerteza no custo de contratos indexados ao IPCA. Se a banda é de 2 pp, seu orçamento tem essa incerteza embutida — dimensione reservas de contingência usando o Máximo como cenário de estresse.

👤 **Investidor Pessoa Física**
Banda muito larga significa que nem os especialistas têm convicção sobre a inflação futura. Nesse cenário, diversifique entre Tesouro IPCA+ e Tesouro Selic em vez de concentrar em uma única estratégia.
""",
        ("IPCA", "revisoes"): """
**O que este gráfico mostra:**
A variação da mediana de uma semana para a outra. Barras **verdes** indicam que o mercado revisou a projeção para **cima** (ficou mais pessimista com inflação). Barras **vermelhas** indicam revisão para **baixo** (ficou mais otimista). As linhas tracejadas marcam o threshold configurado na sidebar.

**Como usar — por perfil:**

💼 **Assessores de Investimento e CFP®**
Use semanas com barra verde acima do threshold como gatilho de revisão de carteira. Exemplo: barra verde acima de +0,10 no IPCA é sinal para contato proativo com clientes com prefixados longos e discussão sobre migração para IPCA+. Barras vermelhas consecutivas são a janela ideal para travar taxas prefixadas.

📊 **Gestores de RPPS**
Sequência de barras verdes (revisões para cima) sinaliza pressão crescente na meta atuarial — acione o comitê de investimentos antes da próxima reunião formal para revisar a política de investimentos com antecedência.

🏦 **Economistas e Analistas de Mercado**
Analise em quais semanas do mês as revisões são mais frequentes. Revisões concentradas após divulgação do IPCA-15 ou reuniões do Copom revelam quais eventos têm maior impacto no consenso — útil para calibrar modelos de nowcasting.

🏢 **Empresas e Tesourarias Corporativas**
Prefira renovar contratos indexados ao IPCA após semanas de barras vermelhas (revisão para baixo) — o mercado está mais otimista e as condições de negociação tendem a ser melhores.

👤 **Investidor Pessoa Física**
Sequência de barras verdes é o sinal mais direto e atualizado de que o mercado está ficando mais preocupado com inflação. Se você está em dúvida entre prefixado e IPCA+, esse padrão é um argumento concreto a favor do IPCA+.
""",
        ("IPCA", "tabela"): """
**O que esta tabela mostra:**
As 8 observações mais recentes do Boletim Focus para o IPCA, com todas as estatísticas do consenso semana a semana.

**Como ler cada coluna:**
- **Data**: semana de publicação do Focus
- **Mediana**: projeção central — metade das instituições projeta abaixo, metade acima
- **Média**: se acima da mediana, há outliers pessimistas; se abaixo, outliers otimistas
- **Desvio Padrão**: abaixo de 0,30 indica consenso forte; acima de 0,50 indica mercado dividido
- **Mínimo**: a instituição mais otimista com a inflação naquela semana
- **Máximo**: a instituição mais pessimista
- **Revisão**: positivo = mais pessimismo; negativo = mais otimismo vs semana anterior
- **Amplitude**: diferença Máximo–Mínimo — proxy direto de incerteza

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Use a coluna Revisão como termômetro semanal. Três revisões positivas consecutivas justificam contato com clientes com prefixados longos. Observe também se o Mínimo está subindo — quando até o mais otimista revisa para cima, o movimento é consistente e merece atenção imediata.

📊 **Gestores de RPPS**
Compare a Mediana atual com sua meta atuarial toda semana. Use o Máximo como cenário de estresse — se mesmo no pior caso os ativos IPCA+ da carteira ainda batem a meta, a política de investimentos está robusta.

🏦 **Economistas**
Desvio Padrão caindo com Mediana subindo = consenso de alta se formando de forma ordenada. Desvio subindo com Mediana estável = mercado dividido sem direção clara — sinal de risco latente não capturado pela mediana.

🏢 **Empresas**
Use a coluna Máximo como base para o orçamento de contratos indexados ao IPCA. Dimensione reservas de contingência para o cenário pessimista, não apenas para a Mediana.

👤 **Pessoa Física**
Coluna Revisão positiva por 3 semanas consecutivas é o sinal mais concreto para avaliar migração de prefixado para IPCA+ na próxima aplicação.
""",
        ("Selic", "mediana"): """
**O que este gráfico mostra:**
A trajetória do consenso de mercado para a taxa básica de juros no ano selecionado. É o principal balizador para decisões de alocação em renda fixa.

**Como usar — por perfil:**

💼 **Assessores de Investimento e CFP®**
Mediana em queda favorece prefixados e IPCA+ longos (que se valorizam quando juros caem). Mediana em alta favorece pós-fixados (Selic/CDI). Exemplo: se a mediana projeta Selic caindo de 13% para 10%, é momento de alongar duration — travar taxas altas antes dos cortes se materializarem.

📊 **Gestores de RPPS**
A Selic projetada define o custo de oportunidade da carteira. Se a mediana projeta Selic a 12% e sua meta atuarial é IPCA+5,5%, avalie se aumentar alocação em pós-fixados garante a meta com menor risco de mercado do que manter duration longa.

🏦 **Economistas e Analistas de Mercado**
Use o histórico da mediana para medir a credibilidade do forward guidance do Copom. Se o mercado consistentemente projeta Selic acima do que o Copom sinaliza, há prêmio de risco embutido — oportunidade de arbitragem para casas com visão diferente do consenso.

🏢 **Empresas e Tesourarias Corporativas**
Dívidas atreladas ao CDI ficam mais caras quando a mediana da Selic sobe. Use as projeções para antecipar o custo financeiro e decidir entre manter dívida flutuante ou fazer swap para prefixado antes que o movimento se consolide.

👤 **Investidor Pessoa Física**
Mediana da Selic em queda é o sinal para migrar parte do Tesouro Selic para Prefixado ou IPCA+ — aproveite as taxas mais altas antes dos cortes reduzirem o retorno do pós-fixado.
""",
        ("Selic", "dispersao"): """
**O que este gráfico mostra:**
Divergência entre instituições sobre o nível futuro da Selic. Banda larga significa que o mercado está dividido sobre o ritmo e a profundidade do ciclo de juros.

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Dispersão alta em torno da Selic indica incerteza sobre o Copom. Evite recomendar prefixados longos nesse cenário — o risco de duration é elevado quando o mercado não sabe onde a Selic vai parar.

📊 **Gestores de RPPS**
Banda larga na Selic complica o ALM. Se há 3 pp de diferença entre o mais otimista e o mais pessimista, a projeção de retorno da carteira pós-fixada tem essa margem de incerteza — seja conservador nas premissas do relatório atuarial.

🏦 **Economistas**
Compare a dispersão da Selic com a dispersão do IPCA. Se ambas estão largas simultaneamente, o mercado está sem âncora — cenário de alta volatilidade esperada em ativos de renda fixa e câmbio.

🏢 **Empresas**
Banda larga na Selic significa custo de dívida CDI imprevisível. Aumente a parcela de dívida prefixada no passivo para reduzir a exposição à incerteza do ciclo de juros.

👤 **Pessoa Física**
Quando nem os especialistas sabem onde a Selic vai, o Tesouro Selic é o porto seguro — você recebe a taxa vigente sem risco de marcação a mercado negativa.
""",
        ("Selic", "revisoes"): """
**O que este gráfico mostra:**
Quanto o consenso da Selic mudou semana a semana. Barras **verdes** = mercado espera Selic mais alta. Barras **vermelhas** = mercado espera cortes maiores ou mais rápidos.

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Barras vermelhas consecutivas (expectativa de Selic mais baixa) são o melhor momento para recomendar alongamento de duration — travar taxas prefixadas altas antes dos cortes se materializarem. Barras verdes consecutivas favorecem pós-fixados.

📊 **Gestores de RPPS**
Revisões para baixo na Selic (barras vermelhas) reduzem o retorno esperado da parcela pós-fixada — avalie se a alocação atual ainda garante a meta atuarial no novo cenário de juros.

🏦 **Economistas**
Revisões bruscas para cima na Selic (barras verdes grandes) geralmente seguem surpresas de inflação ou mudança de tom do Copom — use como proxy de surpresa de política monetária para calibrar modelos.

🏢 **Empresas**
Barras verdes (Selic mais alta na projeção) significam custo de dívida CDI crescente. Acione o hedge antes que o movimento se consolide nas próximas reuniões do Copom.

👤 **Pessoa Física**
Barras vermelhas grandes (Selic caindo na projeção) são o sinal de ação — migre parte do Tesouro Selic para Prefixado ou IPCA+ antes que as taxas caiam e essa janela se feche.
""",
        ("Selic", "tabela"): """
**O que esta tabela mostra:**
As 8 observações mais recentes do Boletim Focus para a taxa Selic, com todas as estatísticas do consenso semana a semana.

**Como ler cada coluna:**
- **Data**: semana de publicação do Focus
- **Mediana**: projeção central da Selic — referência principal do mercado
- **Média**: acima da mediana indica que alguns esperam Selic muito mais alta; abaixo indica otimistas com cortes agressivos
- **Desvio Padrão**: consenso forte (baixo) ou mercado dividido (alto) sobre o ciclo de juros
- **Mínimo**: instituição que projeta os cortes mais agressivos
- **Máximo**: instituição que projeta manutenção ou alta mais intensa
- **Revisão**: positivo = mercado espera Selic mais alta; negativo = espera cortes maiores
- **Amplitude**: quanto maior, mais dividido o mercado sobre o rumo do Copom

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Revisão negativa por 3 semanas consecutivas é a janela para recomendar alongamento de duration. Observe se o Máximo também está caindo — quando até o mais hawkish revisa para baixo, o ciclo de cortes está consolidado.

📊 **Gestores de RPPS**
Use o Mínimo da Selic projetada como piso de retorno para a parcela pós-fixada no cenário pessimista. Se mesmo nesse cenário a carteira bate a meta atuarial, a alocação está robusta.

🏦 **Economistas**
Desvio Padrão aumentando antes de reunião do Copom indica que o mercado está genuinamente incerto sobre a decisão — maior probabilidade de surpresa e volatilidade pós-reunião.

🏢 **Empresas**
Use a coluna Mediana para atualizar semanalmente o custo projetado da dívida CDI. Acione o CFO quando a revisão acumulada nas últimas 4 semanas superar 0,25 pp para cima.

👤 **Pessoa Física**
Revisão negativa consecutiva (Selic caindo na projeção) é o sinal para avaliar migração parcial do Tesouro Selic para Prefixado ou IPCA+ — use esta tabela para não perder o timing.
""",
        ("PIB", "mediana"): """
**O que este gráfico mostra:**
A trajetória do consenso de mercado para o crescimento econômico do Brasil no ano selecionado.

**Como usar — por perfil:**

💼 **Assessores e CFP®**
PIB em revisão consistente para cima indica economia aquecida — favorece aumento gradual de exposição a risco (ações, FIIs, crédito privado). PIB em revisão para baixo favorece postura defensiva com maior peso em renda fixa conservadora.

📊 **Gestores de RPPS**
PIB crescente geralmente está associado a arrecadação maior e contribuições mais estáveis ao fundo. Use as projeções para antecipar o comportamento do fluxo de caixa do RPPS e comunicar ao ente público com antecedência.

🏦 **Economistas**
Compare a mediana do PIB com a da Selic. PIB subindo com Selic subindo indica economia resiliente ao aperto monetário — relevante para calibrar modelos de equilíbrio e projetar o terminal rate do ciclo atual.

🏢 **Empresas**
PIB projetado crescente justifica investimentos em expansão e revisão para cima das metas de receita. PIB em queda é sinal para segurar capex, reforçar liquidez e construir cenários de contingência.

👤 **Pessoa Física**
PIB em alta sugere mercado de trabalho aquecido e menor risco de recessão — contexto favorável para assumir mais risco na carteira e considerar investimentos de maior prazo.
""",
        ("PIB", "dispersao"): """
**O que este gráfico mostra:**
Divergência entre instituições sobre o ritmo de crescimento da economia. Banda larga indica incerteza sobre o ciclo econômico.

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Dispersão alta no PIB reflete incerteza sobre o ciclo econômico — reduza exposição a ativos de risco e aguarde convergência do consenso antes de aumentar posição em ações ou crédito privado.

📊 **Gestores de RPPS**
Incerteza alta no PIB complica projeções atuariais de longo prazo. Seja conservador nas premissas de crescimento real dos ativos e das contribuições futuras.

🏦 **Economistas**
Dispersão no PIB simultaneamente com dispersão no IPCA indica stagflação em debate — mercado dividido entre recessão e inflação persistente, o cenário mais desafiador para política monetária.

🏢 **Empresas**
Construa cenários otimista e pessimista para o orçamento usando os extremos da banda (Mínimo e Máximo da tabela) em vez de apenas a Mediana.

👤 **Pessoa Física**
Incerteza alta no PIB é sinal para manter reserva de emergência robusta antes de aumentar exposição a investimentos de maior risco ou menor liquidez.
""",
        ("PIB", "revisoes"): """
**O que este gráfico mostra:**
Quanto o consenso de crescimento econômico mudou semana a semana. Barras **verdes** = economia melhor que o esperado (revisão para cima). Barras **vermelhas** = perspectivas piorando (revisão para baixo).

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Cluster de barras verdes consecutivas é sinal de melhora do humor econômico — janela para aumentar gradualmente exposição a risco. Barras vermelhas consecutivas justificam postura defensiva.

📊 **Gestores de RPPS**
Revisões para baixo no PIB (barras vermelhas) podem antecipar pressão nas contribuições do ente público. Comunique ao gestor do ente com antecedência — não espere o relatório mensal.

🏦 **Economistas**
Compare Revisão do PIB com Revisão do IPCA na mesma semana. Ambos subindo = economia superaquecida, pressão para Copom apertar mais. PIB caindo com IPCA subindo = stagflação emergindo.

🏢 **Empresas**
Barras verdes consecutivas justificam revisão para cima das metas de receita. Barras vermelhas consecutivas são sinal de alerta para corte de custos preventivo antes que a desaceleração chegue ao resultado.

👤 **Pessoa Física**
Sequência de barras vermelhas no PIB é sinal de cautela — reforce a reserva de emergência antes de aumentar risco ou comprometer liquidez em investimentos de longo prazo.
""",
        ("PIB", "tabela"): """
**O que esta tabela mostra:**
As 8 observações mais recentes do Boletim Focus para o crescimento do PIB, com todas as estatísticas do consenso semana a semana.

**Como ler cada coluna:**
- **Data**: semana de publicação do Focus
- **Mediana**: projeção central de crescimento do PIB
- **Média**: acima da mediana indica otimistas extremos; abaixo indica pessimistas puxando a média
- **Desvio Padrão**: alto indica incerteza sobre o ciclo econômico
- **Mínimo**: projeção mais pessimista — se negativo, alguma instituição projeta recessão
- **Máximo**: projeção mais otimista — economia superaquecida no cenário extremo
- **Revisão**: positivo = perspectivas melhorando; negativo = deterioração das expectativas
- **Amplitude**: divergência entre otimistas e pessimistas sobre o rumo da economia

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Três revisões positivas consecutivas justificam aumentar gradualmente exposição a risco. Observe se o Mínimo está subindo — quando até o mais pessimista melhora sua projeção, o ciclo de alta está consolidado.

📊 **Gestores de RPPS**
Use o Mínimo como base para o cenário conservador de contribuições futuras. Se o mais pessimista projeta PIB de 0,5%, planeje o fluxo de caixa do RPPS considerando esse cenário.

🏦 **Economistas**
Compare Revisão do PIB com Revisão do IPCA e da Selic na mesma semana para montar uma visão integrada do ciclo econômico semana a semana.

🏢 **Empresas**
Use Mínimo para orçamento conservador e Máximo para orçamento otimista — construa o planejamento financeiro dentro dessa banda em vez de apostar em um único número.

👤 **Pessoa Física**
Mínimo negativo (alguma instituição projeta recessão) é sinal de cautela máxima — priorize liquidez e reserva de emergência antes de qualquer investimento de longo prazo.
""",
        ("Câmbio", "mediana"): """
**O que este gráfico mostra:**
A trajetória do consenso de mercado para a taxa de câmbio USD/BRL no ano selecionado. É o termômetro direto do risco-país percebido pelas instituições financeiras.

**Como usar — por perfil:**

💼 **Assessores de Investimento e CFP®**
Câmbio projetado em alta (real depreciando) é argumento direto para recomendar diversificação internacional. Exemplo: se a mediana projeta dólar a R$6,00 e o cliente tem 100% em ativos locais, ele está exposto à depreciação do real sem nenhuma proteção. Fundos cambiais, BDRs e ETFs internacionais são instrumentos acessíveis para essa proteção.

📊 **Gestores de RPPS**
A Resolução CMN 4.963 permite alocação em ativos no exterior dentro de limites específicos. Câmbio em tendência de alta é um dos argumentos técnicos para usar esse espaço regulatório. Documente a projeção do Focus como embasamento formal na ata do comitê de investimentos.

🏦 **Economistas**
A mediana do câmbio é termômetro do risco-país. Compare com os juros futuros para calcular o diferencial de juros implícito e identificar se há carry trade sustentável ou se o mercado está precificando deterioração fiscal.

🏢 **Empresas importadoras**
Câmbio projetado em alta significa custo de insumos importados crescente. Contrate hedge cambial (NDF, opções) quando a mediana estiver em trajetória de alta consistente. **Exportadoras:** o inverso — câmbio alto favorece receita em BRL, mas proteja-se contra reversão brusca travando parte da receita futura.

👤 **Investidor Pessoa Física**
Mediana do câmbio em alta consistente é o sinal mais direto para diversificar parte da carteira em dólar. Fundos cambiais, remessa para conta internacional (Wise, Nomad) ou BDRs são formas acessíveis e regulamentadas de proteção.
""",
        ("Câmbio", "dispersao"): """
**O que este gráfico mostra:**
Divergência entre instituições sobre o nível futuro do dólar. Banda larga indica alta incerteza cambial — momento de maior volatilidade esperada.

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Dispersão alta no câmbio indica volatilidade cambial elevada — recomende diversificação gradual em vez de entrada concentrada. Aportes mensais em fundo cambial são mais prudentes do que uma posição única em momento de banda larga.

📊 **Gestores de RPPS**
Banda larga no câmbio aumenta o risco de ativos internacionais na carteira. Se já há alocação em fundos com exposição cambial, monitore o impacto no VaR e considere reduzir temporariamente a posição até o mercado convergir.

🏦 **Economistas**
Dispersão alta no câmbio combinada com dispersão alta na Selic indica crise de confiança sistêmica — o mercado não tem âncora nem em juros nem em câmbio. Cenário historicamente associado a episódios de fuga de capitais.

🏢 **Empresas**
A Amplitude entre Mínimo e Máximo é a sua margem de incerteza orçamentária em câmbio. Se a banda é de R$1,00, o custo de importação pode variar R$1,00 por dólar — dimensione o hedge para o cenário pessimista (Máximo), não para a Mediana.

👤 **Pessoa Física**
Banda larga é sinal para não tentar adivinhar o timing do câmbio. Entre de forma gradual com aportes mensais em fundo cambial em vez de concentrar em uma única entrada.
""",
        ("Câmbio", "revisoes"): """
**O que este gráfico mostra:**
Quanto o consenso do câmbio mudou semana a semana. Barras **verdes** = dólar subindo na projeção (real depreciando). Barras **vermelhas** = dólar caindo na projeção (real valorizando).

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Três semanas consecutivas de barras verdes (dólar subindo na projeção) justificam contato proativo com clientes sem proteção cambial. Mostre o gráfico como evidência concreta do movimento antes de propor a diversificação internacional.

📊 **Gestores de RPPS**
Barras verdes valorizam ativos internacionais já na carteira em reais — registre o impacto positivo no relatório de rentabilidade. Barras vermelhas (real valorizando) reduzem o retorno em BRL desses ativos — avalie se é momento de realizar lucro.

🏦 **Economistas**
Compare revisões do câmbio com eventos políticos e fiscais. Revisões bruscas para cima (barras verdes grandes) geralmente seguem deterioração fiscal, crise política ou piora do risco externo — use como proxy de risco soberano percebido semana a semana.

🏢 **Empresas importadoras**
Barras verdes grandes são alertas imediatos para contratar hedge. Não espere o câmbio subir para agir — o Focus já mostra que o mercado está revisando. **Exportadoras:** barras vermelhas (real valorizando) são sinal para travar contratos de exportação a taxas mais favoráveis antes da queda.

👤 **Pessoa Física**
Barra verde grande no câmbio (dólar subindo muito na projeção em uma semana) é o sinal mais urgente para avaliar proteção cambial — mesmo que seja uma posição pequena em fundo cambial ou BDR, agir antes do movimento se consolidar faz diferença.
""",
        ("Câmbio", "tabela"): """
**O que esta tabela mostra:**
As 8 observações mais recentes do Boletim Focus para a taxa de câmbio USD/BRL, com todas as estatísticas do consenso semana a semana.

**Como ler cada coluna:**
- **Data**: semana de publicação do Focus
- **Mediana**: projeção central do dólar em reais — referência principal do mercado
- **Média**: acima da mediana indica pessimistas com o real puxando a média; abaixo indica otimistas
- **Desvio Padrão**: consenso forte (baixo) ou mercado dividido (alto) sobre o câmbio
- **Mínimo**: instituição que projeta o real mais valorizado (menor cotação do dólar)
- **Máximo**: instituição que projeta o real mais depreciado (maior cotação do dólar)
- **Revisão**: positivo = dólar subindo na projeção; negativo = dólar caindo
- **Amplitude**: quanto maior, mais incerto o mercado sobre o câmbio futuro

**Como usar — por perfil:**

💼 **Assessores e CFP®**
Três semanas consecutivas de Revisão positiva (dólar subindo) justificam ligação proativa para clientes sem proteção cambial. Observe também se o Mínimo está subindo — quando até o mais otimista com o real está revisando para cima, o movimento tem consistência.

📊 **Gestores de RPPS**
Use a coluna Máximo como cenário de estresse para o VaR cambial da carteira. Se já há ativos internacionais, calcule o impacto em BRL usando o Máximo como câmbio de estresse no relatório mensal.

🏦 **Economistas**
Compare Amplitude do câmbio com Amplitude da Selic na mesma semana. Ambas largas simultaneamente indicam crise de confiança — mercado sem âncora em juros nem em câmbio.

🏢 **Empresas importadoras**
Use o Máximo como base para contratar hedge — se ainda é lucrativo importando ao câmbio mais pessimista, a operação está protegida. **Exportadoras:** use o Mínimo como piso de receita em BRL para avaliar a viabilidade das exportações no pior cenário.

👤 **Pessoa Física**
Coluna Revisão positiva por 3 semanas consecutivas é o sinal mais concreto e atualizado para iniciar uma posição em proteção cambial — não espere o dólar já ter subido para agir.
""",
    }

    return conteudo.get((ind, grafico), "_Conteúdo não disponível para esta combinação._")


# ── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Focus Bulletin Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "app_logged_init" not in st.session_state:
    logger.info(
        "Dashboard iniciado — Focus Bulletin Tracker | %s",
        datetime.now().strftime("%Y-%m-%d"),
    )
    st.session_state["app_logged_init"] = True

# ── CSS customizado ───────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        /* Cabeçalho da sidebar */
        [data-testid="stSidebar"] .block-container { padding-top: 1rem; }

        /* Rodapé */
        .footer {
            text-align: center;
            color: #888;
            font-size: 12px;
            margin-top: 48px;
            padding-top: 16px;
            border-top: 1px solid #333;
        }
        .footer a { color: #00d4ff; text-decoration: none; }
        .footer a:hover { text-decoration: underline; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📊 Focus Tracker")
    st.caption("Expectativas de mercado — Banco Central do Brasil")
    st.divider()

    # Seleção do indicador
    indicador = st.selectbox(
        "Indicador",
        options=list(INDICADORES.keys()),
        index=0,
        help="Indicador macroeconômico a ser analisado",
    )

    # Seleção do ano de referência
    anos = anos_disponiveis()
    ano_atual = str(datetime.now().year)
    idx_padrao = anos.index(ano_atual) if ano_atual in anos else 0
    ano_ref = st.selectbox(
        "Ano de Referência",
        options=anos,
        index=idx_padrao,
        help="Ano para o qual os analistas estão fazendo projeções",
    )

    # Threshold de revisão relevante
    threshold = st.slider(
        "Threshold de Revisão",
        min_value=0.01,
        max_value=1.0,
        value=0.10,
        step=0.01,
        format="%.2f",
        help="Revisões da mediana acima deste valor serão destacadas nos gráficos",
    )

    st.divider()

    # Botão para forçar atualização ignorando o cache
    forcar = st.button(
        "🔄 Forçar Atualização",
        help="Busca dados frescos na API, ignorando o cache local (24h)",
        use_container_width=True,
    )

    st.caption(f"Cache local: 24 h  |  {datetime.now().strftime('%d/%m/%Y %H:%M')}")

logger.info("Seleção: %s / %s", indicador, ano_ref)

# ── Cabeçalho principal ───────────────────────────────────────────────────────
st.title("🇧🇷 Focus Bulletin Tracker")
st.markdown(
    f"Análise histórica das projeções de **{indicador}** para **{ano_ref}** "
    "coletadas semanalmente pelo Banco Central do Brasil."
)

# ── Coleta de dados ───────────────────────────────────────────────────────────
# Ao forçar atualização, limpa o CSV em disco e o cache em memória do Streamlit
# antes de buscar, para garantir que nenhuma camada sirva dado obsoleto.
if forcar:
    limpar_cache_disco(indicador, ano_ref)
    _buscar_dados.clear()

with st.spinner(f"Buscando dados de {indicador} ({ano_ref})…"):
    try:
        df_raw = _buscar_dados(indicador, ano_ref)
    except RuntimeError as erro:
        st.error(f"❌ {erro}")
        st.info(
            "💡 **Dica:** Verifique sua conexão com a internet. "
            "Os dados são buscados diretamente em `olinda.bcb.gov.br`."
        )
        st.stop()

if df_raw.empty:
    logger.warning("Nenhum dado retornado para %s/%s", indicador, ano_ref)
    st.warning(
        f"⚠️ Nenhum dado encontrado para **{indicador}** "
        f"com ano de referência **{ano_ref}** em nenhuma fonte disponível. "
        "Tente outro indicador ou outro ano."
    )
    st.stop()

# Aviso contextual quando os dados vêm do Top5Anuais (Câmbio 2028+).
# Detectado pela ausência da coluna baseCalculo, presente apenas no endpoint anual pleno.
if "baseCalculo" not in df_raw.columns:
    st.info(
        "ℹ️ **Fonte alternativa:** os dados de câmbio para este ano de referência "
        "provêm do endpoint **ExpectativasMercadoTop5Anuais** (5 melhores instituições "
        "por histórico de acerto), não do consenso pleno de ~130 participantes. "
        "Os valores podem divergir ligeiramente do Boletim Focus oficial."
    )

# ── Pipeline analítico ────────────────────────────────────────────────────────
df_full = calcular_pipeline_completo(df_raw, threshold_revisao=threshold)

# Filtro de janela de datas (usa datas reais do dataset carregado)
with st.sidebar:
    st.divider()
    data_min = df_full["Data"].min().date()
    data_max = df_full["Data"].max().date()

    janela = st.date_input(
        "Janela de Datas",
        value=(data_min, data_max),
        min_value=data_min,
        max_value=data_max,
        help="Restrinja o período exibido nos gráficos e tabela",
    )

# Aplica filtro temporal
if isinstance(janela, (list, tuple)) and len(janela) == 2:
    df = df_full[
        (df_full["Data"].dt.date >= janela[0]) & (df_full["Data"].dt.date <= janela[1])
    ].copy()
else:
    df = df_full.copy()

if df.empty:
    st.warning("⚠️ A janela de datas selecionada não contém observações.")
    st.stop()

# ── Métricas resumidas ────────────────────────────────────────────────────────
resumo = resumo_estatistico(df)

col1, col2, col3, col4 = st.columns(4)

with col1:
    ultima = resumo.get("Última Mediana", 0) or 0
    st.metric(
        label=f"Última Mediana ({indicador})",
        value=f"{ultima:.2f}",
    )

with col2:
    variacao = resumo.get("Variação no Período", 0) or 0
    st.metric(
        label="Variação no Período",
        value=f"{variacao:+.2f}",
        delta=f"{variacao:+.2f}",
    )

with col3:
    _MESES_PT = {
        1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
        7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
    }
    _fmt = lambda d: f"{_MESES_PT[d.month]}/{d.strftime('%y')}"
    periodo = f"{_fmt(df['Data'].min())} – {_fmt(df['Data'].max())}"
    st.metric(label="Período Analisado", value=periodo)

with col4:
    amp = resumo.get("Máx. Dispersão", 0) or 0
    st.metric(
        label="Máx. Amplitude (Max – Min)",
        value=f"{amp:.2f}",
        help="Maior diferença entre projeção máxima e mínima no período",
    )

st.divider()

# ── Gráfico 1: Evolução da mediana ────────────────────────────────────────────
st.subheader("📈 Evolução da Mediana")
st.caption("Trajetória semanal da mediana e da média das projeções dos analistas")

with st.expander("📖 Como ler este gráfico?"):
    st.markdown(get_expander_content(indicador, "mediana"))

fig1 = go.Figure()

# Linha da mediana
fig1.add_trace(
    go.Scatter(
        x=df["Data"],
        y=df["Mediana"],
        mode="lines+markers",
        name="Mediana",
        line=dict(color="#00d4ff", width=2),
        marker=dict(size=5),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Mediana: %{y:.2f}<extra></extra>",
    )
)

# Linha da média (tracejada)
fig1.add_trace(
    go.Scatter(
        x=df["Data"],
        y=df["Media"],
        mode="lines",
        name="Média",
        line=dict(color="#ff9900", width=1.5, dash="dot"),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Média: %{y:.2f}<extra></extra>",
    )
)

# Destaca semanas com revisão relevante
df_rel = df[df.get("RevisaoRelevante", pd.Series(False, index=df.index)) == True]
if not df_rel.empty:
    fig1.add_trace(
        go.Scatter(
            x=df_rel["Data"],
            y=df_rel["Mediana"],
            mode="markers",
            name=f"Revisão > ±{threshold:.2f}",
            marker=dict(color="#ff4b4b", size=11, symbol="star"),
            customdata=df_rel["Revisao"].round(3),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>"
                "Mediana: %{y:.2f}<br>"
                "Revisão: %{customdata:+.3f}<extra></extra>"
            ),
        )
    )

fig1.update_layout(
    template="plotly_dark",
    height=400,
    xaxis_title="Data",
    yaxis_title=indicador,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
    margin=dict(l=0, r=0, t=30, b=0),
)

try:
    st.plotly_chart(fig1, width="stretch")
except Exception as _e:
    logger.error("Erro ao renderizar gráfico de mediana (%s/%s): %s", indicador, ano_ref, _e, exc_info=True)
    st.error("❌ Erro ao renderizar o gráfico de mediana.")

# ── Gráfico 2: Banda de dispersão ─────────────────────────────────────────────
st.subheader("🎯 Dispersão do Mercado")
st.caption(
    "Banda entre projeções mínima e máxima dos participantes — "
    "área maior indica maior incerteza"
)

with st.expander("📖 Como ler este gráfico?"):
    st.markdown(get_expander_content(indicador, "dispersao"))

fig2 = go.Figure()

# Área sombreada entre Mínimo e Máximo
x_band = pd.concat([df["Data"], df["Data"][::-1]])
y_band = pd.concat([df["Maximo"], df["Minimo"][::-1]])

fig2.add_trace(
    go.Scatter(
        x=x_band,
        y=y_band,
        fill="toself",
        fillcolor="rgba(0, 212, 255, 0.12)",
        line=dict(color="rgba(255,255,255,0)"),
        name="Amplitude (Max–Min)",
        hoverinfo="skip",
    )
)

# Linha do máximo
fig2.add_trace(
    go.Scatter(
        x=df["Data"],
        y=df["Maximo"],
        mode="lines",
        name="Máximo",
        line=dict(color="rgba(0, 212, 255, 0.45)", width=1, dash="dash"),
        hovertemplate="Máx: %{y:.2f}<extra></extra>",
    )
)

# Linha do mínimo
fig2.add_trace(
    go.Scatter(
        x=df["Data"],
        y=df["Minimo"],
        mode="lines",
        name="Mínimo",
        line=dict(color="rgba(0, 212, 255, 0.45)", width=1, dash="dash"),
        hovertemplate="Mín: %{y:.2f}<extra></extra>",
    )
)

# Banda ±1 desvio padrão (referência estatística)
if "DesvioPadrao" in df.columns and df["DesvioPadrao"].notna().any():
    fig2.add_trace(
        go.Scatter(
            x=df["Data"],
            y=df["Mediana"] + df["DesvioPadrao"],
            mode="lines",
            name="+1σ",
            line=dict(color="rgba(255, 153, 0, 0.4)", width=1, dash="dot"),
            hovertemplate="+1σ: %{y:.2f}<extra></extra>",
        )
    )
    fig2.add_trace(
        go.Scatter(
            x=df["Data"],
            y=df["Mediana"] - df["DesvioPadrao"],
            mode="lines",
            name="-1σ",
            line=dict(color="rgba(255, 153, 0, 0.4)", width=1, dash="dot"),
            hovertemplate="-1σ: %{y:.2f}<extra></extra>",
        )
    )

# Mediana sobreposta à banda
fig2.add_trace(
    go.Scatter(
        x=df["Data"],
        y=df["Mediana"],
        mode="lines+markers",
        name="Mediana",
        line=dict(color="#00d4ff", width=2.5),
        marker=dict(size=4),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Mediana: %{y:.2f}<extra></extra>",
    )
)

fig2.update_layout(
    template="plotly_dark",
    height=420,
    xaxis_title="Data",
    yaxis_title=indicador,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
    margin=dict(l=0, r=0, t=30, b=0),
)

try:
    st.plotly_chart(fig2, width="stretch")
except Exception as _e:
    logger.error("Erro ao renderizar gráfico de dispersão (%s/%s): %s", indicador, ano_ref, _e, exc_info=True)
    st.error("❌ Erro ao renderizar o gráfico de dispersão.")

# ── Gráfico 3: Revisões semanais ──────────────────────────────────────────────
st.subheader("🔄 Revisões Semanais da Mediana")
st.caption(
    f"Variação semana a semana — barras verdes: revisão para cima | "
    f"vermelhas: revisão para baixo | linhas tracejadas: threshold ±{threshold:.2f}"
)

with st.expander("📖 Como ler este gráfico?"):
    st.markdown(get_expander_content(indicador, "revisoes"))

df_rev = df.dropna(subset=["Revisao"])

if not df_rev.empty:
    cores = ["#2ecc71" if r >= 0 else "#e74c3c" for r in df_rev["Revisao"]]

    fig3 = go.Figure()

    fig3.add_trace(
        go.Bar(
            x=df_rev["Data"],
            y=df_rev["Revisao"],
            marker_color=cores,
            name="Revisão Semanal",
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>"
                "Revisão: %{y:+.3f}<extra></extra>"
            ),
        )
    )

    # Linha de zero
    fig3.add_hline(y=0, line_color="white", line_width=0.5, opacity=0.3)

    # Linhas de threshold
    fig3.add_hline(
        y=threshold,
        line_color="#ff4b4b",
        line_width=1,
        line_dash="dash",
        annotation_text=f"+{threshold:.2f}",
        annotation_position="top right",
    )
    fig3.add_hline(
        y=-threshold,
        line_color="#ff4b4b",
        line_width=1,
        line_dash="dash",
        annotation_text=f"-{threshold:.2f}",
        annotation_position="bottom right",
    )

    fig3.update_layout(
        template="plotly_dark",
        height=350,
        xaxis_title="Data",
        yaxis_title="Revisão da Mediana",
        showlegend=False,
        margin=dict(l=0, r=0, t=30, b=0),
    )

    try:
        st.plotly_chart(fig3, width="stretch")
    except Exception as _e:
        logger.error("Erro ao renderizar gráfico de revisões (%s/%s): %s", indicador, ano_ref, _e, exc_info=True)
        st.error("❌ Erro ao renderizar o gráfico de revisões.")
else:
    st.info("ℹ️ Dados insuficientes para calcular revisões semanais no período selecionado.")

# ── Tabela: Últimas 8 semanas ─────────────────────────────────────────────────
st.subheader("📋 Últimas 8 Semanas")

with st.expander("📖 Como ler esta tabela?"):
    st.markdown(get_expander_content(indicador, "tabela"))

df_tab = ultimas_semanas(df, n=8).copy()

if not df_tab.empty:
    # Seleciona e renomeia colunas para exibição
    colunas_exibir = {
        "Data": "Data",
        "Mediana": "Mediana",
        "Media": "Média",
        "DesvioPadrao": "Desvio Padrão",
        "Minimo": "Mínimo",
        "Maximo": "Máximo",
        "Revisao": "Revisão",
        "Amplitude": "Amplitude",
    }
    colunas_presentes = [c for c in colunas_exibir if c in df_tab.columns]
    df_display = df_tab[colunas_presentes].rename(columns=colunas_exibir).copy()

    # Formata data
    df_display["Data"] = pd.to_datetime(df_display["Data"]).dt.strftime("%d/%m/%Y")

    # Arredonda numéricas
    numericas = ["Mediana", "Média", "Desvio Padrão", "Mínimo", "Máximo", "Revisão", "Amplitude"]
    for col in numericas:
        if col in df_display.columns:
            df_display[col] = df_display[col].round(3)

    # Aplica estilo condicional à coluna Revisão
    def _cor_revisao(val):
        if pd.isna(val):
            return ""
        if val > threshold:
            return "color: #2ecc71; font-weight: bold"
        if val < -threshold:
            return "color: #e74c3c; font-weight: bold"
        return "color: #cccccc"

    styled = df_display.style.map(_cor_revisao, subset=["Revisão"])
    st.dataframe(styled, width="stretch", hide_index=True)
else:
    st.info("Nenhum dado disponível para exibição.")

# ── Análise de Erro do Consenso ───────────────────────────────────────────────
st.divider()
st.subheader("🎯 Análise de Erro do Consenso")
st.caption(
    "Compara as medianas históricas do Focus com os valores efetivamente realizados"
)

if indicador == "Câmbio":
    st.info(
        "ℹ️ A análise de erro do consenso não está disponível para Câmbio. "
        "A taxa de câmbio oscila continuamente ao longo do ano e não possui "
        "um valor \"realizado\" oficial único comparável às projeções do Focus."
    )
else:
    with st.spinner("Buscando valores realizados e histórico de projeções…"):
        df_realizados_hist = _buscar_realizados(indicador)
        df_historico_proj = _buscar_todos_anos(indicador)

    if df_realizados_hist.empty:
        st.warning(
            "⚠️ Não foi possível obter valores realizados para este indicador. "
            "Verifique sua conexão com a internet."
        )
    elif df_historico_proj.empty:
        st.warning("⚠️ Sem histórico de projeções disponível para o cálculo.")
    else:
        df_erros = calcular_erro_consenso(df_historico_proj, df_realizados_hist)

        if df_erros.empty:
            st.info(
                "ℹ️ Dados insuficientes para calcular o erro do consenso. "
                "São necessários anos com projeções históricas e valor realizado disponível."
            )
        else:
            # ── Cards de resumo ───────────────────────────────────────────────
            erro_medio = df_erros["erro"].mean()
            erro_abs_medio = df_erros["erro_absoluto"].mean()
            vies = "Pessimista" if erro_medio > 0 else "Otimista"

            col_e1, col_e2, col_e3 = st.columns(3)
            with col_e1:
                st.metric(
                    label="Erro Médio Histórico",
                    value=f"{erro_medio:+.2f} pp",
                    help="Positivo = mercado superestimou; Negativo = subestimou",
                )
            with col_e2:
                st.metric(
                    label="Erro Absoluto Médio",
                    value=f"{erro_abs_medio:.2f} pp",
                    help="Magnitude média do erro, independente da direção",
                )
            with col_e3:
                st.metric(
                    label="Viés do Consenso",
                    value=vies,
                    help=(
                        "Otimista = mercado subestimou sistematicamente (realizou acima do projetado). "
                        "Pessimista = mercado superestimou (realizou abaixo do projetado)."
                    ),
                )

            # ── Gráfico: erro médio por horizonte ─────────────────────────────
            st.caption("Erro Médio por Horizonte de Projeção")

            erros_h = (
                df_erros.groupby("horizonte_semanas")["erro"]
                .mean()
                .reset_index()
                .sort_values("horizonte_semanas", ascending=False)
            )
            labels_h = [str(h) for h in erros_h["horizonte_semanas"]]
            cores_h = ["#e74c3c" if e > 0 else "#2ecc71" for e in erros_h["erro"]]

            fig_err = go.Figure()
            fig_err.add_trace(
                go.Bar(
                    x=labels_h,
                    y=erros_h["erro"].tolist(),
                    marker_color=cores_h,
                    name="Erro médio",
                    hovertemplate=(
                        "<b>%{x} sem. antes</b><br>"
                        "Erro médio: %{y:+.3f} pp<extra></extra>"
                    ),
                )
            )
            fig_err.add_hline(y=0, line_color="white", line_width=1, opacity=0.4)
            fig_err.update_layout(
                template="plotly_dark",
                height=320,
                xaxis_title="Semanas antes do final do ano",
                yaxis_title="Erro médio (pp)",
                showlegend=False,
                margin=dict(l=0, r=0, t=20, b=0),
                xaxis=dict(categoryorder="array", categoryarray=labels_h),
            )

            try:
                st.plotly_chart(fig_err, width="stretch")
            except Exception as _e:
                logger.error(
                    "Erro ao renderizar gráfico de erro do consenso (%s): %s",
                    indicador, _e, exc_info=True,
                )
                st.error("❌ Erro ao renderizar o gráfico de erro do consenso.")

            # ── Tabela: erro por ano (horizonte 52 semanas) ───────────────────
            st.caption("Erro por Ano — horizonte de 52 semanas antes de 31/dezembro")

            df_52 = df_erros[df_erros["horizonte_semanas"] == 52].copy()
            if not df_52.empty:
                df_tab_err = (
                    df_52[["ano", "mediana_projetada", "valor_realizado", "erro", "erro_absoluto"]]
                    .sort_values("ano", ascending=False)
                    .reset_index(drop=True)
                    .copy()
                )
                df_tab_err.columns = [
                    "Ano", "Projeção (52 sem.)", "Realizado", "Erro (pp)", "Erro Absoluto",
                ]
                for col in ["Projeção (52 sem.)", "Realizado", "Erro (pp)", "Erro Absoluto"]:
                    df_tab_err[col] = df_tab_err[col].round(2)

                def _cor_err_col(val):
                    if pd.isna(val):
                        return ""
                    if val > 0:
                        return "color: #e74c3c; font-weight: bold"
                    if val < 0:
                        return "color: #2ecc71; font-weight: bold"
                    return "color: #cccccc"

                styled_err = df_tab_err.style.map(_cor_err_col, subset=["Erro (pp)"])
                st.dataframe(styled_err, width="stretch", hide_index=True)
            else:
                st.info("ℹ️ Sem dados para o horizonte de 52 semanas.")

            with st.expander("📖 Como ler esta análise?"):
                st.markdown(get_erro_consenso_content(indicador))

# ── Rodapé ────────────────────────────────────────────────────────────────────
ultima_obs = df["Data"].max().strftime("%d/%m/%Y") if not df.empty else "—"

st.markdown(
    f"""
    <div class="footer">
        📊 <strong>Focus Bulletin Tracker</strong> &nbsp;|&nbsp;
        Fonte:
        <a href="https://www.bcb.gov.br/publicacoes/focus" target="_blank">
            Boletim Focus — Banco Central do Brasil
        </a>
        &nbsp;|&nbsp;
        API:
        <a href="https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/swagger-ui3"
           target="_blank">
            BCB Olinda
        </a>
        &nbsp;|&nbsp;
        Última observação no conjunto: <strong>{ultima_obs}</strong>
        &nbsp;|&nbsp;
        Dashboard gerado em: <strong>{datetime.now().strftime("%d/%m/%Y %H:%M")}</strong>
    </div>
    """,
    unsafe_allow_html=True,
)

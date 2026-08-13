from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from llm import chamar_llm, extrair_json
from schemas import ExtracaoLLM
from validators import (
    encontrar_cliente_conhecido,
    nome_presente_no_texto_ou_conhecido,
    numero_processo_presente_no_texto,
    numero_processo_valido,
)

logger = logging.getLogger(__name__)

"""
Responsável por realizar a chamada ao LLM e validar a resposta de acordo
com o schema definido.

Caso a resposta seja malformada ou não esteja em conformidade com o schema,
uma nova tentativa é realizada. O tratamento de erros de rede e respectivas
tentativas de reconexão são realizados internamente pela função `chamar_llm`;
nesta etapa, o retry é específico para falhas de formato ou validação da
resposta.
"""
def _chamar_e_validar(mensagem: dict, temperature: float) -> ExtracaoLLM | None:
    for tentativa in range(2): # Realiza tentativas para a LLM, caso não consiga, ou o resultado retorne errado, retorna None
        bruto = chamar_llm(mensagem, temperature=temperature) # Chama a função que comunica com o LLM em llm.py e recebe o resultado bruto
        try:
            dados = extrair_json(bruto) # Chama a função em llm.py para limpar o resultado
            return ExtracaoLLM.model_validate(dados) # Chama a função do Modelo de resposta correto esperado da LLM em schemas.py para validação da resposta
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(
                "Resposta do LLM fora do formato esperado (tentativa %d) para msg %s: %s",
                tentativa + 1,
                mensagem.get("id"),
                e,
            )
    return None

"""
Função responsável pela classificação das mensagens utilizando duas
execuções do LLM com diferentes valores de temperatura.

Os resultados são comparados para verificar a concordância entre as
classificações. Em caso de divergência, um modelo arbitral é acionado para
analisar as respostas e determinar a classificação final.

Ao final do processo, o resultado validado é processado e retornado pela
função.
"""
def classificar_mensagem(mensagem: dict, clientes: list[dict]) -> dict:
    observacoes: list[str] = []

    # Chamada dos dois resultados
    resultado_a = _chamar_e_validar(mensagem, temperature=0.0)
    resultado_b = _chamar_e_validar(mensagem, temperature=0.4)

    # Tratamento de caso de falha em cetegorizar
    if resultado_a is None and resultado_b is None:
        # LLM falhou nas duas tentativas,
        # Marcado claramente para triagem humana.
        return _resultado_fallback(mensagem, observacoes, "Falha ao obter resposta válida do LLM")
    if resultado_a is None:
        resultado_a = resultado_b
        observacoes.append("Primeira chamada falhou; usada apenas a segunda.")
    if resultado_b is None:
        resultado_b = resultado_a
        observacoes.append("Segunda chamada falhou; usada apenas a primeira.")

    concordam = resultado_a.categoria == resultado_b.categoria
    final = resultado_a # Pega um dos resultados

    if not concordam:
        arbitro = _arbitrar(mensagem, resultado_a, resultado_b) # Chama a função de arbitragem para corrigir a discordancia
        if arbitro is not None and arbitro.categoria in (resultado_a.categoria, resultado_b.categoria): # Confere se o arbitro escolheu com sentido
            final = arbitro
            observacoes.append(
                f"Divergência entre chamadas ({resultado_a.categoria} vs {resultado_b.categoria}); "
                f"arbitragem decidiu por '{arbitro.categoria}'."
            )
        else:
            observacoes.append(
                f"Divergência não resolvida entre chamadas ({resultado_a.categoria} vs "
                f"{resultado_b.categoria}); mantida a de temperature=0 e sinalizada para revisão."
            )

    return _pos_processar(mensagem, final, clientes, concordam, observacoes) # chama a função que processa o resultado da LLM para o formato JSON utilizado para os resultados

"""
Função responsável pela arbitragem das classificações quando ocorre
divergência entre os resultados obtidos pelos classificadores.
"""
def _arbitrar(mensagem: dict, a: ExtracaoLLM, b: ExtracaoLLM) -> ExtracaoLLM | None:
    prompt_arbitragem = dict(mensagem)
    prompt_arbitragem["texto"] = (  #Cria o Pronpt para realizar a arbitrazem dos resultados
        f"{mensagem['texto']}\n\n"
        f"[ARBITRAGEM] Duas análises anteriores desta MESMA mensagem divergiram: "
        f"uma classificou como '{a.categoria}' e outra como '{b.categoria}'. "
        f"Releia a mensagem com atenção e decida qual das duas categorias está "
        f"correta (responda apenas com uma delas), mantendo o mesmo formato de saída."
    )
    resultado = _chamar_e_validar(prompt_arbitragem, temperature=0.0) # Chama a função para chamar a LLM
    return resultado

"""
Executa a rotina de fallback caso a saída do modelo (LLM) apresente inconsistências 
ou falhe na validação de esquema, retornando uma resposta com a categoria padrão (default).
"""
def _resultado_fallback(mensagem: dict, observacoes: list[str], motivo: str) -> dict:
    observacoes.append(motivo)
    return {
        "id": mensagem["id"],
        "canal": mensagem["canal"],
        "de": mensagem["de"],
        "data_recebimento": mensagem["data_recebimento"],
        "texto": mensagem["texto"],
        "categoria": "duvida_processo",  # categoria neutra, nunca "spam" nem some do resumo, mudar conforme o escolhido
        "nome_cliente": None,
        "numero_processo": None,
        "data_prazo": None,
        "resumo": "Não foi possível processar automaticamente esta mensagem.",
        "cliente_conhecido": False,
        "concordancia_dupla_checagem": False,
        "revisar_manualmente": True,
        "observacoes": observacoes,
    }



"""
Função responsável por processar e normalizar a resposta retornada pela LLM, adequando-a ao formato 
esperado pelo banco de dados e, quando aplicável, incorporando informações adicionais que contribuam 
para a identificação e diferenciação dos registros, como o nome do cliente.
"""
def _pos_processar(
    mensagem: dict,
    extracao: ExtracaoLLM,
    clientes: list[dict],
    concordam: bool,
    observacoes: list[str],
) -> dict:
    texto = mensagem["texto"]
    numero_processo = extracao.numero_processo
    nome_cliente = extracao.nome_cliente
    cliente_conhecido = False

    # anti-alucinação da LLM
    if numero_processo: # Garantir que o Numero do Processo estaja no formato correto
        if not numero_processo_valido(numero_processo): # chama função de validação em validators.py
            observacoes.append(f"numero_processo '{numero_processo}' não tem formato CNJ válido; descartado.")
            numero_processo = None
        elif not numero_processo_presente_no_texto(numero_processo, texto):
            observacoes.append(f"numero_processo '{numero_processo}' não aparece literalmente no texto; descartado.")
            numero_processo = None
    if nome_cliente and not nome_presente_no_texto_ou_conhecido(nome_cliente, texto): # garantir que o nome do cliente, caso presente na menssagem exista
        observacoes.append(f"nome_cliente '{nome_cliente}' não aparece no texto; descartado.")
        nome_cliente = None

    cliente = encontrar_cliente_conhecido(mensagem["de"], clientes) # Procura pelo Cliente na arquivo de clientes existentes pelo método de mandar a menssagem
    if cliente:
        cliente_conhecido = True
        if not nome_cliente:
            nome_cliente = cliente["nome"]
            observacoes.append("nome_cliente preenchido via base de clientes conhecidos (remetente já cadastrado).")
        if not numero_processo and cliente.get("processo"):
            numero_processo = cliente["processo"]
            observacoes.append("numero_processo preenchido via base de clientes conhecidos.")

    revisar = (not concordam and "arbitragem decidiu" not in " ".join(observacoes)) or ( # Revisão final para caso a menssagem precisa ser revisada manualmente 
        extracao.categoria == "urgente_prazo" and not extracao.data_prazo
    )
    if extracao.categoria == "urgente_prazo" and not extracao.data_prazo:
        observacoes.append("Classificada como urgente_prazo mas sem data_prazo extraída; conferir manualmente.")

    return {
        "id": mensagem["id"],
        "canal": mensagem["canal"],
        "de": mensagem["de"],
        "data_recebimento": mensagem["data_recebimento"],
        "texto": texto,
        "categoria": extracao.categoria,
        "nome_cliente": nome_cliente,
        "numero_processo": numero_processo,
        "data_prazo": extracao.data_prazo,
        "resumo": extracao.resumo,
        "cliente_conhecido": cliente_conhecido,
        "concordancia_dupla_checagem": concordam,
        "revisar_manualmente": bool(revisar),
        "observacoes": observacoes,
    }

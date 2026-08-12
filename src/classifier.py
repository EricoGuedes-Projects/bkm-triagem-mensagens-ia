"""
Núcleo da "dupla checagem" exigida no teste.

Estratégia adotada (e por que):
  1. Chamamos o LLM DUAS vezes para a mesma mensagem, com temperature=0.0
     e temperature=0.4. Se ambas concordam na categoria, aceitamos com
     confiança alta.
  2. Se divergem, fazemos uma TERCEIRA chamada de "arbitragem": mostramos
     ao LLM as duas respostas divergentes e pedimos para decidir qual é
     a correta, com base apenas no texto original. Isso funciona melhor
     do que só pegar a maioria, porque força uma nova leitura do texto.
  3. Se mesmo a arbitragem não conseguir decidir (ou o resultado da
     arbitragem não é uma das duas categorias propostas), marcamos
     revisar_manualmente=True e a mensagem cai destacada no resumo diário
     em vez de ser roteada silenciosamente errada.
  4. Independente da concordância, aplicamos validators.py (regex CNJ,
     presença literal no texto) para pegar alucinações que passariam
     despercebidas mesmo com as duas chamadas concordando.

Isso é mais caro que uma chamada só (2-3x o custo por mensagem), mas para
o volume do escritório (~500 msgs/dia) o custo extra é pequeno perto do
risco de rotear uma intimação urgente para a categoria errada.
"""
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


def _chamar_e_validar(mensagem: dict, temperature: float) -> ExtracaoLLM | None:
    """Chama o LLM e valida contra o schema. Se o JSON vier malformado ou
    fora do schema, tenta mais uma vez (o retry de rede já está em
    chamar_llm; aqui é retry de FORMATO)."""
    for tentativa in range(2):
        bruto = chamar_llm(mensagem, temperature=temperature)
        try:
            dados = extrair_json(bruto)
            return ExtracaoLLM.model_validate(dados)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(
                "Resposta do LLM fora do formato esperado (tentativa %d) para msg %s: %s",
                tentativa + 1,
                mensagem.get("id"),
                e,
            )
    return None


def classificar_mensagem(mensagem: dict, clientes: list[dict]) -> dict:
    """Retorna um dict pronto para virar MensagemProcessada."""
    observacoes: list[str] = []

    resultado_a = _chamar_e_validar(mensagem, temperature=0.0)
    resultado_b = _chamar_e_validar(mensagem, temperature=0.4)

    if resultado_a is None and resultado_b is None:
        # LLM falhou nas duas tentativas duplas: não travamos o lote,
        # mas marcamos claramente para triagem humana.
        return _resultado_fallback(mensagem, observacoes, "Falha ao obter resposta válida do LLM")

    if resultado_a is None:
        resultado_a = resultado_b
        observacoes.append("Primeira chamada falhou; usada apenas a segunda.")
    if resultado_b is None:
        resultado_b = resultado_a
        observacoes.append("Segunda chamada falhou; usada apenas a primeira.")

    concordam = resultado_a.categoria == resultado_b.categoria
    final = resultado_a

    if not concordam:
        arbitro = _arbitrar(mensagem, resultado_a, resultado_b)
        if arbitro is not None and arbitro.categoria in (resultado_a.categoria, resultado_b.categoria):
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

    return _pos_processar(mensagem, final, clientes, concordam, observacoes)


def _arbitrar(mensagem: dict, a: ExtracaoLLM, b: ExtracaoLLM) -> ExtracaoLLM | None:
    prompt_arbitragem = dict(mensagem)
    prompt_arbitragem["texto"] = (
        f"{mensagem['texto']}\n\n"
        f"[ARBITRAGEM] Duas análises anteriores desta MESMA mensagem divergiram: "
        f"uma classificou como '{a.categoria}' e outra como '{b.categoria}'. "
        f"Releia a mensagem com atenção e decida qual das duas categorias está "
        f"correta (responda apenas com uma delas), mantendo o mesmo formato de saída."
    )
    resultado = _chamar_e_validar(prompt_arbitragem, temperature=0.0)
    return resultado


def _resultado_fallback(mensagem: dict, observacoes: list[str], motivo: str) -> dict:
    observacoes.append(motivo)
    return {
        "id": mensagem["id"],
        "canal": mensagem["canal"],
        "de": mensagem["de"],
        "data_recebimento": mensagem["data_recebimento"],
        "texto": mensagem["texto"],
        "categoria": "duvida_processo",  # categoria neutra, nunca "spam" nem some do resumo
        "nome_cliente": None,
        "numero_processo": None,
        "data_prazo": None,
        "resumo": "Não foi possível processar automaticamente esta mensagem.",
        "cliente_conhecido": False,
        "concordancia_dupla_checagem": False,
        "revisar_manualmente": True,
        "observacoes": observacoes,
    }


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

    # --- anti-alucinação: número de processo ---
    if numero_processo:
        if not numero_processo_valido(numero_processo):
            observacoes.append(f"numero_processo '{numero_processo}' não tem formato CNJ válido; descartado.")
            numero_processo = None
        elif not numero_processo_presente_no_texto(numero_processo, texto):
            observacoes.append(f"numero_processo '{numero_processo}' não aparece literalmente no texto; descartado.")
            numero_processo = None

    # --- anti-alucinação: nome do cliente ---
    if nome_cliente and not nome_presente_no_texto_ou_conhecido(nome_cliente, texto):
        observacoes.append(f"nome_cliente '{nome_cliente}' não aparece no texto; descartado.")
        nome_cliente = None

    # --- bônus: enriquecimento por base de clientes conhecidos ---
    cliente = encontrar_cliente_conhecido(mensagem["de"], clientes)
    if cliente:
        cliente_conhecido = True
        if not nome_cliente:
            nome_cliente = cliente["nome"]
            observacoes.append("nome_cliente preenchido via base de clientes conhecidos (remetente já cadastrado).")
        if not numero_processo and cliente.get("processo"):
            numero_processo = cliente["processo"]
            observacoes.append("numero_processo preenchido via base de clientes conhecidos.")

    revisar = (not concordam and "arbitragem decidiu" not in " ".join(observacoes)) or (
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

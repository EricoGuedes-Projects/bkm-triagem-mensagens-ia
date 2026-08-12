"""
Camada de acesso ao LLM.

Usamos a API da Anthropic (Claude) por padrão. Trocar de provedor é
questão de reimplementar `chamar_llm()` — o resto do pipeline não sabe
nem se importa qual LLM está por trás, porque a interface é
"prompt in -> string JSON out".

Se ANTHROPIC_API_KEY não estiver configurada, cai em MOCK_MODE: gera uma
resposta determinística e simplificada só para permitir rodar o pipeline
ponta a ponta offline (dev/demo). MOCK_MODE nunca deve ser usado para
avaliar qualidade de classificação — ele existe apenas para não travar
quem for rodar o projeto sem uma chave de API à mão.
"""
from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
API_KEY = os.getenv("OPENAI_API_KEY")
MOCK_MODE = not API_KEY

PROMPT_SISTEMA = """Você é um assistente de triagem de mensagens para um escritório de advocacia.

Sua tarefa é classificar a mensagem em UMA das categorias:
- urgente_prazo
- duvida_processo
- agendamento
- financeiro
- documento_recebido
- spam_irrelevante

Além disso, extraia, quando existirem:
- nome do cliente
- número do processo no formato CNJ
- data ou prazo mencionado
- resumo da mensagem em uma frase

REGRAS:
1. Não invente informações.
2. Se uma informação não estiver presente, retorne null.
3. Não altere números de processo.
4. Datas devem ser retornadas no formato YYYY-MM-DD quando
   houver informação suficiente para determinar a data.
5. Uma mensagem com prazo judicial deve ser considerada
   urgente_prazo quando houver um prazo definido ou iminente.
6. Mensagens de advogados da parte contrária também podem
   ser urgentes.
7. Preste atenção a mensagens relacionadas a pagamento e 
   afins como financeiro.
8. Diferencie documentos enviados de dúvidas sobre documentos.
9. Não classifique baseado apenas em uma palavra isolada.
   Considere o contexto completo da mensagem.
10. Retorne somente o JSON solicitado.

Formato de saída (APENAS este JSON, sem texto antes ou depois, sem markdown):
{
  "categoria": "<uma das 6 categorias>",
  "nome_cliente": "<string ou null>",
  "numero_processo": "<string no formato CNJ ou null>",
  "data_prazo": "<YYYY-MM-DD ou null>",
  "resumo": "<uma frase>"
}"""


def _montar_prompt_usuario(mensagem: dict) -> str:
    return (
        f"Canal: {mensagem['canal']}\n"
        f"Remetente: {mensagem['de']}\n"
        f"Data de recebimento: {mensagem['data_recebimento']}\n"
        f"Texto da mensagem: \"\"\"{mensagem['texto']}\"\"\"\n\n"
        "Classifique e extraia os campos conforme as instruções do sistema. "
        "Use a data de recebimento como referência para interpretar expressões "
        "relativas como 'amanhã', 'semana que vem' etc., convertendo para YYYY-MM-DD "
        "sempre que a mensagem permitir determinar a data com segurança; caso "
        "contrário, retorne null em vez de adivinhar."
    )


# @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
# def chamar_llm(mensagem: dict, temperature: float = 0.0) -> str:
#     """Faz UMA chamada ao LLM e devolve a string JSON crua (ainda não
#     validada com Pydantic — isso é feito em classifier.py)."""
#     if MOCK_MODE:
#         return _mock_resposta(mensagem)

#     import anthropic

#     client = anthropic.Anthropic(api_key=API_KEY)
#     resp = client.messages.create(
#         model=MODEL,
#         max_tokens=500,
#         temperature=temperature,
#         system=PROMPT_SISTEMA,
#         messages=[{"role": "user", "content": _montar_prompt_usuario(mensagem)}],
#     )
#     texto = "".join(b.text for b in resp.content if b.type == "text")
#     return texto

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def chamar_llm(mensagem: dict, temperature: float = 0.0) -> str:
    from openai import OpenAI
 
    client = OpenAI(api_key=API_KEY)
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=temperature,
        max_tokens=500,
        # força a saída a ser um JSON object válido — evita que o modelo
        # cerque a resposta com texto/markdown, então não precisamos nem
        # do extrair_json() de limpeza para esse provedor (mas mantemos
        # a limpeza mesmo assim, por segurança/portabilidade).
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": _montar_prompt_usuario(mensagem)},
        ],
    )
    return resp.choices[0].message.content or ""


def extrair_json(texto_bruto: str) -> dict:
    """O LLM às vezes cerca o JSON com ```json ... ``` mesmo quando pedimos
    para não fazer isso. Isso limpa esses casos antes do json.loads()."""
    limpo = texto_bruto.strip()
    limpo = re.sub(r"^```(json)?", "", limpo).strip()
    limpo = re.sub(r"```$", "", limpo).strip()
    return json.loads(limpo)


def _mock_resposta(mensagem: dict) -> str:
    """Modo offline/demo (sem API key). NÃO usa regras de negócio reais —
    apenas garante que o pipeline roda ponta a ponta para fins de teste
    de infraestrutura. Ver aviso no README."""
    texto = mensagem["texto"].lower()
    if "promo" in texto or "consorcio" in texto or "consórcio" in texto:
        cat = "spam_irrelevante"
    elif "intima" in texto or "prazo" in texto or "manifest" in texto:
        cat = "urgente_prazo"
    elif "horario" in texto or "horário" in texto or "marcar" in texto or "audiencia" in texto or "audiência" in texto:
        cat = "agendamento"
    elif "pagamento" in texto or "honorár" in texto or "acordo" in texto or "r$" in texto:
        cat = "financeiro"
    elif "anexo" in texto or "segue" in texto or "laudo" in texto or "foto" in texto or "ctps" in texto:
        cat = "documento_recebido"
    else:
        cat = "duvida_processo"

    m = re.search(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", mensagem["texto"])
    return json.dumps(
        {
            "categoria": cat,
            "nome_cliente": None,
            "numero_processo": m.group(0) if m else None,
            "data_prazo": None,
            "resumo": mensagem["texto"][:80],
        }
    )

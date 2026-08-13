"""
Validações que rodam DEPOIS do LLM responder, sem depender dele.

A ideia é simples: o LLM é bom para interpretar linguagem natural, mas não é
confiável como fonte de verdade sobre "esse número existe literalmente no
texto?". Isso a gente confere com Python puro (regex / substring), que é
determinístico e barato.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

CNJ_REGEX = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")

"""
Função que Confere se a string tem exatamente o formato CNJ esperado.
"""
def numero_processo_valido(numero: str | None) -> bool:
    if not numero:
        return False
    return bool(CNJ_REGEX.fullmatch(numero.strip()))

"""
Função de proteção contra Anti-alucinação, o número de processo só é aceito se aparecer
literalmente no texto original da mensagem.
"""
def numero_processo_presente_no_texto(numero: str | None, texto: str) -> bool:
    if not numero:
        return True  # nada a checar
    return numero.strip() in texto

"""
Função de proteção contra Anti-alucinação, aceita se o nome (ou parte dele)
aparece no texto.
"""
def nome_presente_no_texto_ou_conhecido(nome: str | None, texto: str) -> bool:
    if not nome:
        return True
    partes = nome.split()
    texto_norm = _normaliza(texto)
    return any(_normaliza(p) in texto_norm for p in partes if len(p) > 2)

# Funções de Normalização
def _normaliza(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower()


def normaliza_telefone(numero: str) -> str:
    return re.sub(r"\D", "", numero or "")


def normaliza_email(email: str) -> str:
    return (email or "").strip().lower()

"""
Função responsável por gerar uma chave hash de deduplicação a partir do remetente
e do conteúdo da mensagem, utilizando os dados normalizados para garantir
a identificação consistente de mensagens duplicadas ou já processadas.
"""
def hash_mensagem(de: str, texto: str) -> str:
    base = f"{normaliza_telefone(de) or normaliza_email(de)}|{_normaliza(texto).strip()}"
    return hashlib.sha256(base.encode()).hexdigest()

"""
Função que cruza o remetente da mensagem com uma base de clientes já
cadastrados (telefone ou e-mail), permitindo preencher nome_cliente e
numero_processo mesmo quando a mensagem não os menciona explicitamente.
"""
def encontrar_cliente_conhecido(de: str, clientes: list[dict]) -> dict | None:
    tel = normaliza_telefone(de)
    mail = normaliza_email(de)
    for c in clientes:
        if tel and c.get("telefone") and normaliza_telefone(c["telefone"]) == tel:
            return c
        if mail and c.get("email") and normaliza_email(c["email"]) == mail:
            return c
    return None

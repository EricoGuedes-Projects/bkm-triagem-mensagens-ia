"""
Schemas de dados usados no pipeline.

A saída do LLM é sempre validada contra `ExtracaoLLM` antes de ser aceita.
Isso é o que nos protege de:
  - o modelo inventar um campo que não pediu-se (campo extra é ignorado)
  - o modelo devolver uma categoria fora da lista fechada (erro de validação -> retry)
  - o modelo devolver uma data em formato errado (erro de validação -> retry)
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

CATEGORIAS = (
    "urgente_prazo",
    "duvida_processo",
    "agendamento",
    "financeiro",
    "documento_recebido",
    "spam_irrelevante",
)

Categoria = Literal[
    "urgente_prazo",
    "duvida_processo",
    "agendamento",
    "financeiro",
    "documento_recebido",
    "spam_irrelevante",
]

"""
Classe que representa o formato exato esperado da resposta da LLM da chamada de classificação 
para a mensagem que sera usada para extração
"""
class ExtracaoLLM(BaseModel):

    categoria: Categoria
    nome_cliente: Optional[str] = None
    numero_processo: Optional[str] = None
    data_prazo: Optional[str] = None
    resumo: str

    @field_validator("numero_processo")
    @classmethod
    def valida_formato_cnj(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        import re

        # formato CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO
        if not re.fullmatch(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", v.strip()):
            # Não derrubamos o pipeline por isso: marcamos como suspeito e deixamos o validators.py decidir se descarta (possível alucinação de formato) em vez de estourar uma exceção de parsing aqui.
            return v.strip()
        return v.strip()

    @field_validator("data_prazo")
    @classmethod
    def valida_formato_data(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(
                f"data_prazo deve estar em YYYY-MM-DD, recebido: {v!r}"
            ) from exc
        return v

"""
Classe que representa o registro final no banco de dados já com metadados
da dupla checagem e das validações anti-alucinação.
"""
class MensagemProcessada(BaseModel):

    id: int
    canal: str
    de: str
    data_recebimento: str
    texto: str
    categoria: Categoria
    nome_cliente: Optional[str] = None
    numero_processo: Optional[str] = None
    data_prazo: Optional[str] = None
    resumo: str
    cliente_conhecido: bool = False
    concordancia_dupla_checagem: bool
    revisar_manualmente: bool
    observacoes: list[str] = Field(default_factory=list)

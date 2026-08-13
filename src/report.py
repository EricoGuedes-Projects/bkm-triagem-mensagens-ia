from __future__ import annotations

from collections import Counter
from datetime import date

from schemas import CATEGORIAS

NOMES_CATEGORIA = {
    "urgente_prazo": "Urgente / Prazo",
    "duvida_processo": "Dúvida sobre processo",
    "agendamento": "Agendamento",
    "financeiro": "Financeiro",
    "documento_recebido": "Documento recebido",
    "spam_irrelevante": "Spam / Irrelevante",
}

"""
Função que gera o relaório com as mensagens por catedoria e mostra as mensagens urgentes ou que precisam de revisão manual
"""
def gerar_resumo(registros: list[dict], data_referencia: str | None = None) -> str:
    data_referencia = data_referencia or date.today().isoformat()
    contagem = Counter(r["categoria"] for r in registros)
    total = len(registros)
    revisar = [r for r in registros if r["revisar_manualmente"]]

    linhas = [
        f"RESUMO DIÁRIO DE TRIAGEM — {data_referencia}",
        "=" * 50,
        f"Total de mensagens processadas: {total}",
        "",
        "Por categoria:",
    ]
    for cat in CATEGORIAS:
        linhas.append(f"  - {NOMES_CATEGORIA[cat]}: {contagem.get(cat, 0)}")

    urgentes = [r for r in registros if r["categoria"] == "urgente_prazo"]
    urgentes.sort(key=lambda r: (r["data_prazo"] is None, r["data_prazo"] or ""))

    linhas.append("")
    linhas.append(f"URGENTES / COM PRAZO ({len(urgentes)}) — mais próximas primeiro:")
    if not urgentes:
        linhas.append("  (nenhuma)")
    for r in urgentes:
        prazo = r["data_prazo"] or "prazo não identificado — CONFERIR"
        cliente = r["nome_cliente"] or "(remetente não identificado como cliente)"
        processo = f" | processo {r['numero_processo']}" if r["numero_processo"] else ""
        linhas.append(f"  [{prazo}] {cliente}{processo} — {r['resumo']} (canal: {r['canal']}, de: {r['de']})")

    if revisar:
        linhas.append("")
        linhas.append(f"⚠ MENSAGENS PARA REVISÃO MANUAL ({len(revisar)}):")
        for r in revisar:
            linhas.append(f"  - #{r['id']} ({r['categoria']}): {'; '.join(r['observacoes'])}")

    return "\n".join(linhas)

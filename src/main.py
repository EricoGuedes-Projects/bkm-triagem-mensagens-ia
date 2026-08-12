"""
Ponto de entrada.

Simulação do recebimento: em vez de integração real com WhatsApp/e-mail
(que exigiria conta Meta aprovada), este script funciona como um "watcher
de arquivo" — lê data/input/messages.json como se fosse a fila de mensagens
novas chegando. A arquitetura foi pensada para que, no lugar dessa leitura
de arquivo, entre um endpoint de webhook (ex.: FastAPI) recebendo o mesmo
formato de mensagem e chamando exatamente o mesmo `pipeline.py` por
mensagem — nada no classifier/validators/database muda.

Uso:
    python src/main.py
    python src/main.py --input caminho/outro_arquivo.json
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from classifier import classificar_mensagem
from database import buscar_todos, conectar, ja_processada, salvar
from llm import MOCK_MODE
from report import gerar_resumo
from validators import hash_mensagem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA_PADRAO = RAIZ / "data" / "input" / "messages.json"
CLIENTES_PADRAO = RAIZ / "data" / "clients.json"
SAIDA_JSON = RAIZ / "data" / "output" / "results.json"
SAIDA_RESUMO = RAIZ / "data" / "output" / "resumo_diario.txt"
CAMINHO_DB = RAIZ / "data" / "output" / "triagem.db"


def carregar_json(caminho: Path) -> list[dict]:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def executar(caminho_entrada: Path) -> list[dict]:
    if MOCK_MODE:
        logger.warning(
            "ANTHROPIC_API_KEY não configurada — rodando em MOCK_MODE "
            "(classificação heurística simplificada, apenas para demo offline "
            "da arquitetura; NÃO representa a qualidade da solução final)."
        )

    mensagens = carregar_json(caminho_entrada)
    clientes = carregar_json(CLIENTES_PADRAO) if CLIENTES_PADRAO.exists() else []
    conn = conectar(str(CAMINHO_DB))

    resultados: list[dict] = []
    ignoradas_dedup = 0

    for msg in mensagens:
        h = hash_mensagem(msg["de"], msg["texto"])
        if ja_processada(conn, h):
            ignoradas_dedup += 1
            logger.info("Mensagem #%s ignorada: duplicata já processada anteriormente.", msg["id"])
            continue

        logger.info("Processando mensagem #%s (%s)...", msg["id"], msg["canal"])
        registro = classificar_mensagem(msg, clientes)
        salvar(conn, registro, h)
        resultados.append(registro)

    # O JSON/resumo exportados refletem TODO o histórico no banco, não só
    # o lote desta execução — assim rodar o script de novo (ex.: watcher
    # disparando a cada novo lote de mensagens) não perde o que já foi
    # processado antes.
    todos_registros = buscar_todos(conn)
    conn.close()

    SAIDA_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA_JSON, "w", encoding="utf-8") as f:
        json.dump(todos_registros, f, ensure_ascii=False, indent=2)

    resumo = gerar_resumo(todos_registros)
    with open(SAIDA_RESUMO, "w", encoding="utf-8") as f:
        f.write(resumo)

    logger.info(
        "Concluído: %d novas mensagens processadas neste lote, %d ignoradas por deduplicação. "
        "Total acumulado no banco: %d.",
        len(resultados),
        ignoradas_dedup,
        len(todos_registros),
    )
    print("\n" + resumo + "\n")
    print(f"JSON completo salvo em: {SAIDA_JSON}")
    print(f"Banco SQLite salvo em: {CAMINHO_DB}")
    return resultados


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Triagem inteligente de mensagens de clientes")
    parser.add_argument("--input", type=str, default=str(ENTRADA_PADRAO), help="Caminho do JSON de entrada")
    args = parser.parse_args()
    executar(Path(args.input))

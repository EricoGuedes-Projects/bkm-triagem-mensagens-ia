from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from classifier import classificar_mensagem
from database import buscar_todos, conectar, ja_processada, salvar, buscar_por_dia
from llm import MOCK_MODE
from report import gerar_resumo
from validators import hash_mensagem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Caminhos utilizados na execução
RAIZ = Path(__file__).resolve().parent.parent
ENTRADA_PADRAO = RAIZ / "data" / "input" / "messages.json"
CLIENTES_PADRAO = RAIZ / "data" / "clients.json"
_DATA_HOJE = date.today().isoformat()
SAIDA_JSON = RAIZ / "data" / "output" / f"results_{_DATA_HOJE}.json"
SAIDA_RESUMO = RAIZ / "data" / "output" / f"resumo_diario_{_DATA_HOJE}.txt"
CAMINHO_DB = RAIZ / "data" / "output" / "triagem.db"

"""
Função responsável pela leitura e carregamento dos arquivos JSON utilizados
como dados de entrada da aplicação.
"""
def carregar_json(caminho: Path) -> list[dict]:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)

"""
Função principal responsável pela execução da pipeline de processamento,
orquestrando os módulos do projeto.

Realiza a leitura dos arquivos de entrada, contendo as mensagens e os
clientes, inicializa a conexão com o banco de dados e processa as mensagens
individualmente.

Durante o processamento, são identificadas e descartadas mensagens
duplicadas, enquanto as mensagens válidas são encaminhadas ao módulo de
classificação e extração de dados.

Ao final da execução, os resultados processados são persistidos em formato
JSON e utilizados para a geração do relatório diário.
"""
def executar(caminho_entrada: Path) -> list[dict]:
    if MOCK_MODE: # Aviso que não comunicação com a API da LLM e esta entrando em modo offline
        logger.warning(
            "API_KEY não configurada — rodando em MOCK_MODE "
            "(classificação heurística simplificada, apenas para demo offline "
            "da arquitetura; NÃO representa a resultado final/correto)."
        )

    mensagens = carregar_json(caminho_entrada) # Abre o arquivo de input
    clientes = carregar_json(CLIENTES_PADRAO) if CLIENTES_PADRAO.exists() else [] # Abre o arquivo de Informação de Clientes(Se existir)
    conn = conectar(str(CAMINHO_DB)) # Abre o banco de dados

    resultados: list[dict] = []
    ignoradas_dedup = 0

    for msg in mensagens: # Loop que processa cada menssagem individualmente
        h = hash_mensagem(msg["de"], msg["texto"]) # Chama a Função do validator.py para criar um hash especifico para a menssagem, utilizando ele para comparação de deduplicação
        if ja_processada(conn, h): # chama a função de database.py para ver se essa mensagem ja existe no banco de dados
            ignoradas_dedup += 1
            logger.info("Mensagem #%s ignorada: duplicata já processada anteriormente.", msg["id"])
            continue

        logger.info("Processando mensagem #%s (%s)...", msg["id"], msg["canal"])
        registro = classificar_mensagem(msg, clientes) # chama o classificador de classifiers.py para classificar a categoria
        salvar(conn, registro, h) # salva a mensagen classificadas no banco
        resultados.append(registro)

    # O JSON/resumo exportados refletem TODO o histórico no banco, não só
    # o lote desta execução — assim rodar o script de novo (ex.: watcher
    # disparando a cada novo lote de mensagens) não perde o que já foi
    # processado antes.
    todos_registros = buscar_todos(conn)
    registros_hoje = buscar_por_dia(conn, _DATA_HOJE)
    conn.close()

    SAIDA_JSON.parent.mkdir(parents=True, exist_ok=True) # Cria ou abre o arquivo de saida e escreve os resultados
    with open(SAIDA_JSON, "w", encoding="utf-8") as f:
        json.dump(todos_registros, f, ensure_ascii=False, indent=2)

    resumo = gerar_resumo(registros_hoje) # Chama a função de criação do relatório em report.py
    with open(SAIDA_RESUMO, "w", encoding="utf-8") as f: # Cria ou abre o arquivo de saida e escreve o relatório
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
    parser.add_argument("--input", type=str, default=str(ENTRADA_PADRAO), help="Caminho do JSON de entrada") # Caso deseja-se utilizar outro arquivo de input que não seja menssages.json
    args = parser.parse_args()
    executar(Path(args.input))

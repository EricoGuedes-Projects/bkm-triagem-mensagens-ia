
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS mensagens_processadas (
    id INTEGER PRIMARY KEY,
    hash_dedup TEXT UNIQUE,
    canal TEXT,
    de TEXT,
    data_recebimento TEXT,
    texto TEXT,
    categoria TEXT,
    nome_cliente TEXT,
    numero_processo TEXT,
    data_prazo TEXT,
    resumo TEXT,
    cliente_conhecido INTEGER,
    concordancia_dupla_checagem INTEGER,
    revisar_manualmente INTEGER,
    observacoes TEXT,
    processado_em TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

"""
Função que conecta com o banco de dados sqlite3 usado no projeto
"""
def conectar(caminho_db: str) -> sqlite3.Connection:
    Path(caminho_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho_db)
    conn.execute(SCHEMA)
    conn.commit()
    return conn

"""
Função responsável por utilizar o hash da mensagem para verificar se ela é duplicada 
ou se já foi previamente processada pelo sistema.
"""
def ja_processada(conn: sqlite3.Connection, hash_dedup: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM mensagens_processadas WHERE hash_dedup = ?", (hash_dedup,)
    )
    return cur.fetchone() is not None

"""
Função responsável por recuperar todas as mensagens previamente processadas, 
incluindo aquelas registradas em execuções anteriores, no formato utilizado 
pelo report.py e pelo results.json. Essa abordagem garante a preservação 
do histórico mesmo quando uma nova execução realiza a deduplicação dos dados.
"""
def buscar_todos(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT id, canal, de, data_recebimento, texto, categoria, nome_cliente,
               numero_processo, data_prazo, resumo, cliente_conhecido,
               concordancia_dupla_checagem, revisar_manualmente, observacoes
        FROM mensagens_processadas
        ORDER BY id
        """
    )
    registros = []
    for row in cur.fetchall():
        d = dict(row)
        d["cliente_conhecido"] = bool(d["cliente_conhecido"])
        d["concordancia_dupla_checagem"] = bool(d["concordancia_dupla_checagem"])
        d["revisar_manualmente"] = bool(d["revisar_manualmente"])
        d["observacoes"] = json.loads(d["observacoes"]) if d["observacoes"] else []
        registros.append(d)
    return registros

def buscar_por_dia(conn: sqlite3.Connection, data_iso: str) -> list[dict]:
    """Só as mensagens processadas no dia informado (AAAA-MM-DD, horário local)."""
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT id, canal, de, data_recebimento, texto, categoria, nome_cliente,
               numero_processo, data_prazo, resumo, cliente_conhecido,
               concordancia_dupla_checagem, revisar_manualmente, observacoes,
               processado_em
        FROM mensagens_processadas
        WHERE date(processado_em, 'localtime') = ?
        ORDER BY id
        """,
        (data_iso,),
    )
    return [_linha_para_dict(row) for row in cur.fetchall()]


def _linha_para_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["cliente_conhecido"] = bool(d["cliente_conhecido"])
    d["concordancia_dupla_checagem"] = bool(d["concordancia_dupla_checagem"])
    d["revisar_manualmente"] = bool(d["revisar_manualmente"])
    d["observacoes"] = json.loads(d["observacoes"]) if d["observacoes"] else []
    return d

"""
Função que salva o resultado da menssagem no banco de dados
"""
def salvar(conn: sqlite3.Connection, registro: dict, hash_dedup: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO mensagens_processadas (
            id, hash_dedup, canal, de, data_recebimento, texto, categoria,
            nome_cliente, numero_processo, data_prazo, resumo,
            cliente_conhecido, concordancia_dupla_checagem, revisar_manualmente,
            observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            registro["id"],
            hash_dedup,
            registro["canal"],
            registro["de"],
            registro["data_recebimento"],
            registro["texto"],
            registro["categoria"],
            registro["nome_cliente"],
            registro["numero_processo"],
            registro["data_prazo"],
            registro["resumo"],
            int(registro["cliente_conhecido"]),
            int(registro["concordancia_dupla_checagem"]),
            int(registro["revisar_manualmente"]),
            json.dumps(registro["observacoes"], ensure_ascii=False),
        ),
    )
    conn.commit()

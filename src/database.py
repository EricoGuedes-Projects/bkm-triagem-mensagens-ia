"""
Persistência em SQLite.

Escolhido em vez de Postgres/Sheets para o escopo do teste: zero
infraestrutura extra para rodar (`sqlite3` já vem no Python), arquivo único
fácil de inspecionar, e suficiente para ~500 msgs/dia. Ver README para a
justificativa completa e o plano de migração para Postgres em produção.
"""
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


def conectar(caminho_db: str) -> sqlite3.Connection:
    Path(caminho_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho_db)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def ja_processada(conn: sqlite3.Connection, hash_dedup: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM mensagens_processadas WHERE hash_dedup = ?", (hash_dedup,)
    )
    return cur.fetchone() is not None


def buscar_todos(conn: sqlite3.Connection) -> list[dict]:
    """Devolve todas as mensagens já processadas (de execuções anteriores
    inclusive), na forma usada pelo report.py e pelo results.json. Isso
    evita que uma nova execução com deduplicação 'zere' o histórico."""
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

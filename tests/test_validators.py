import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from validators import (
    encontrar_cliente_conhecido,
    hash_mensagem,
    nome_presente_no_texto_ou_conhecido,
    numero_processo_presente_no_texto,
    numero_processo_valido,
)


def test_numero_processo_valido_aceita_formato_cnj():
    assert numero_processo_valido("0010702-33.2024.5.03.0069")


def test_numero_processo_valido_rejeita_formato_errado():
    assert not numero_processo_valido("123-45")
    assert not numero_processo_valido(None)
    assert not numero_processo_valido("0010702-33.2024.5.3.0069")  # dígito faltando


def test_numero_processo_presente_no_texto_detecta_alucinacao():
    texto = "meu processo 0010702-33.2024.5.03.0069 teve audiencia"
    assert numero_processo_presente_no_texto("0010702-33.2024.5.03.0069", texto)
    assert not numero_processo_presente_no_texto("9999999-99.2099.5.03.9999", texto)


def test_nome_presente_no_texto():
    texto = "Oi, sou a Maria Aparecida, meu processo..."
    assert nome_presente_no_texto_ou_conhecido("Maria Aparecida", texto)
    assert not nome_presente_no_texto_ou_conhecido("Fulano de Tal", texto)


def test_hash_mensagem_e_deduplicacao():
    h1 = hash_mensagem("+5527999990001", "Olá, tudo bem?")
    h2 = hash_mensagem("+55 27 99999-0001", "olá, tudo bem?")  # mesma msg, formatação diferente
    h3 = hash_mensagem("+5527999990001", "Outra mensagem")
    assert h1 == h2
    assert h1 != h3


def test_encontrar_cliente_conhecido_por_telefone():
    clientes = [{"nome": "Maria Aparecida", "telefone": "+5527999990001", "email": None, "processo": "0010702-33.2024.5.03.0069"}]
    encontrado = encontrar_cliente_conhecido("+5527999990001", clientes)
    assert encontrado is not None
    assert encontrado["nome"] == "Maria Aparecida"


def test_encontrar_cliente_conhecido_retorna_none_se_nao_existe():
    clientes = [{"nome": "Maria Aparecida", "telefone": "+5527999990001", "email": None, "processo": None}]
    assert encontrar_cliente_conhecido("+5599999999999", clientes) is None

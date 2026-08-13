import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import classifier

# Mensagem de basica para teste
MENSAGEM_BASE = {
    "id": 1,
    "canal": "whatsapp",
    "de": "+5527999990001",
    "data_recebimento": "2026-08-08",
    "texto": "Oi, sou a Maria Aparecida, meu processo 0010702-33.2024.5.03.0069 teve audiencia marcada?",
}

"""
Define a resposta da LLM para a mensagem de teste
"""
def _resp(categoria: str, **kwargs) -> str:
    base = {
        "categoria": categoria,
        "nome_cliente": "Maria Aparecida",
        "numero_processo": "0010702-33.2024.5.03.0069",
        "data_prazo": None,
        "resumo": "Cliente pergunta sobre audiência do processo.",
    }
    base.update(kwargs)
    return json.dumps(base)

"""
Testa a classificação quando as duas chamadas da LLM retornam a mesma categoria.
Verifica que a dupla checagem é considerada concordante e que a arbitragem e
a revisão manual por divergência não são acionadas.
"""
def test_classificacao_com_concordancia():
    # As duas chamadas (temperature 0.0 e 0.4) concordam -> não deve
    # disparar arbitragem nem marcar para revisão manual por divergência.
    with patch.object(classifier, "chamar_llm", return_value=_resp("duvida_processo")):
        resultado = classifier.classificar_mensagem(MENSAGEM_BASE, clientes=[])

    assert resultado["categoria"] == "duvida_processo"
    assert resultado["concordancia_dupla_checagem"] is True
    assert resultado["revisar_manualmente"] is False
    assert resultado["numero_processo"] == "0010702-33.2024.5.03.0069"

"""
Testa o cenário de divergência entre as duas classificações independentes da LLM.
Verifica que a função de arbitragem é acionada e que sua decisão é utilizada
como categoria final, registrando a ocorrência nas observações.
"""
def test_divergencia_aciona_arbitragem():
    respostas = [
        _resp("duvida_processo"),  # chamada temperature=0.0
        _resp("agendamento"),      # chamada temperature=0.4 (diverge)
        _resp("agendamento"),      # chamada de arbitragem decide por 'agendamento'
    ]

    with patch.object(classifier, "chamar_llm", side_effect=respostas):
        resultado = classifier.classificar_mensagem(MENSAGEM_BASE, clientes=[])

    assert resultado["categoria"] == "agendamento"
    assert resultado["concordancia_dupla_checagem"] is False
    assert any("arbitragem" in obs for obs in resultado["observacoes"])

"""
Testa a validação do número de processo retornado pela LLM.
Verifica que um número de processo inexistente no texto original é considerado
uma alucinação e, portanto, descartado do resultado final.
"""
def test_numero_processo_alucinado_e_descartado():
    # LLM "inventa" um número de processo que não está no texto original.
    resp_alucinada = _resp("duvida_processo", numero_processo="9999999-99.2099.5.03.9999")
    with patch.object(classifier, "chamar_llm", return_value=resp_alucinada):
        resultado = classifier.classificar_mensagem(MENSAGEM_BASE, clientes=[])

    assert resultado["numero_processo"] is None
    assert any("não aparece literalmente no texto" in obs for obs in resultado["observacoes"])

"""
Testa o enriquecimento dos dados a partir de um cliente previamente cadastrado.
Verifica que o cliente é identificado pelo telefone e que seu nome e número
de processo são incorporados ao resultado quando não fornecidos pela LLM.
"""
def test_enriquecimento_por_cliente_conhecido():
    mensagem_sem_nome = dict(MENSAGEM_BASE)
    mensagem_sem_nome["texto"] = "o dr me pediu o laudo do inss, ta aqui a foto"
    mensagem_sem_nome["de"] = "+5527999990004"
    resp = json.dumps(
        {
            "categoria": "documento_recebido",
            "nome_cliente": None,
            "numero_processo": None,
            "data_prazo": None,
            "resumo": "Cliente envia laudo do INSS.",
        }
    )
    clientes = [
        {"nome": "Roberto Nunes", "telefone": "+5527999990004", "email": None, "processo": "0002211-05.2022.5.03.0069"}
    ]

    with patch.object(classifier, "chamar_llm", return_value=resp):
        resultado = classifier.classificar_mensagem(mensagem_sem_nome, clientes=clientes)

    assert resultado["cliente_conhecido"] is True
    assert resultado["nome_cliente"] == "Roberto Nunes"
    assert resultado["numero_processo"] == "0002211-05.2022.5.03.0069"

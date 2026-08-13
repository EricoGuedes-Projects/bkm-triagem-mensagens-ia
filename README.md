# Triagem inteligente de mensagens de clientes 

Pipeline em Python puro que lê
mensagens desestruturadas (WhatsApp/e-mail), classifica com um LLM (com dupla
checagem), extrai campos estruturados, grava em SQLite e gera um resumo diário
em texto.

## Como rodar

```bash
git clone <este-repositorio>
cd teste-automacao-ia
python -m venv .venv  
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python src/main.py
```

Recebendo o input de `data/input/messages.json` , processa cada
mensagem, e gera:

- `data/output/results.json` — todas as mensagens processadas, com categoria,
  campos extraídos e metadados de auditoria (concordância da dupla checagem,
  se precisa revisão manual, observações).
- `data/output/resumo_diario.txt` — o resumo em texto (total por categoria,
  urgentes no topo ordenadas por prazo).
- `data/output/triagem.db` — SQLite com todo o histórico processado.

Rodar de novo com o mesmo arquivo de entrada **não duplica** nada (deduplicação
por hash de remetente+texto) e o `results.json`/resumo sempre 
refletem as mensagens processadas no dia, não só a execução atual.

Para simular um novo lote de mensagens chegando, basta apontar para outro
arquivo no mesmo formato:

```bash
python src/main.py --input data/input/outro_lote.json
```

### Rodar os testes

```bash
pytest tests/ -v
```

Os testes usam mocks do LLM (usando uma reposta de teste basica), cobrindo:
validação de formato CNJ, deduplicação, descarte de número de processo
"alucinado" (que não existe no texto original), e a lógica de arbitragem
quando as duas chamadas do LLM divergem.

## Arquitetura

```
data/input/messages.json (ou webhook/pasta monitorada)
              │
              ▼
        main.py (orquestrador)
              │
              ├─► validators.hash_mensagem()  ──► já processada? ──► pula (dedup)
              │
              ▼
        classifier.classificar_mensagem()
              │
              ├─► llm.chamar_llm()  [temperature=0.0]  ──┐
              ├─► llm.chamar_llm()  [temperature=0.4]  ──┼─► concordam? ──► aceita
              │                                          │
              │                                          └─► divergem? ──► llm.chamar_llm() [arbitragem]
              │
              ├─► schemas.ExtracaoLLM (valida formato/schema, com retry se malformado)
              │
              ├─► validators: CNJ válido? nº processo aparece no texto? nome aparece no texto?
              │       └─► se não passar, campo é descartado (anti-alucinação)
              │
              ├─► validators.encontrar_cliente_conhecido() (bônus: enriquece nome/processo
              │       via data/clients.json quando o remetente já é cliente cadastrado)
              │
              ▼
        database.salvar()  ──► SQLite (data/output/triagem.db)
              │
              ▼
        report.gerar_resumo()  ──► data/output/resumo_diario.txt
        (todo o histórico)  ──► data/output/results.json
```

O "recebimento" é simulado por leitura de arquivo (`data/input/messages.json`), 
de forma a simular uma entrada de dados por fonte externa.
De forma a facilitar uma troca para uma API externa para input de dados
caso necessario.

## Por que essas ferramentas

- **Código puramente em Python.** Para uma tarefa com lógica não-trivial de
  validação, dupla checagem e anti-alucinação, código puro dá controle fino
  sobre cada etapa (retry, comparação de duas respostas, arbitragem) que em
  uma ferramenta de orquestração visual vira caixa-preta difícil de testar
  automaticamente. Código também é testável com `pytest` e versionável com
  diffs legíveis — importante para um escritório que vai querer auditar por
  que uma mensagem caiu em tal categoria.
- **Anthropic API (Claude) como LLM.** Boa relação custo/qualidade para
  extração estruturada e segue instruções de formato de saída de forma
  consistente. A camada `llm.py` isola isso: trocar de provedor é reescrever
  uma função, o resto do pipeline não muda, o que é demostrado pela 
  opção de Utilizar Openai apenas mudando a chamada da API e a função chamar_llm.
- **SQLite como banco de dados.** Para ~500 msgs/dia, um arquivo único
  sem servidor é suficiente, zero infraestrutura para rodar o teste, e ainda
  assim dá histórico consultável via SQL. Migração para Postgres é natural
  quando o uso crescer, podendo ser utilizado facilmente com o uso de docker.
- **Pydantic para validar a saída do LLM.** Garante que "categoria" é sempre
  uma das 6 permitidas e que "data_prazo" é sempre uma data válida ou `null`
  — se o LLM fugir do formato, isso vira um retry automático em vez de um
  dado sujo entrando no banco.

## Como a dupla checagem funciona

De modo a tentar evitar a alucinação sem utilizar classificação por palavras chaves. A solução:

1. Cada mensagem é classificada **duas vezes** (temperatures diferentes, de modo a utilizar a randomização de escolhas de palavras da LLM).
2. Se as duas concordam na categoria, aceita com confiança alta.
3. Se divergem, uma **terceira chamada de arbitragem** mostra ao LLM as duas
   respostas conflitantes e pede para decidir revendo o texto original.
4. Se nem a arbitragem resolver, a mensagem é marcada `revisar_manualmente` e
   aparece destacada no resumo — nunca é roteada silenciosamente errada.
5. Independente da concordância, `numero_processo` e `nome_cliente` só são
   aceitos se aparecerem literalmente no texto original (checagem em Python,
   não no LLM) — isso pega alucinação mesmo quando as duas chamadas
   concordam entre si (concordância não é o mesmo que estar certo).

Para casos em que temos exemplos especiais da massa de teste (mensagem do advogado da parte contrária,
com prazo, deve ser `urgente_prazo`) é coberto por regras especificas do prompt e testado
manualmente na massa fornecida.

## Melhorias Futuras ou Implementações para maior scala

- **Cache de prompt** (system prompt é idêntico em toda chamada) para reduzir
  custo — a Anthropic API cobra ~10% do preço normal em tokens de cache hit.
- **Fila assíncrona** (ex.: Celery/RQ) em vez de loop síncrono, para não
  bloquear o webhook de recebimento enquanto o LLM responde.
- **Endpoint FastAPI real** substituindo a leitura de arquivo, com validação
  de assinatura do webhook do canal (WhatsApp Business API/Twilio).
- **Postgres** no lugar do SQLite quando o volume ou o número de usuários
  simultâneos crescer, e para permitir consulta concorrente pelo time enquanto
  o pipeline continua gravando.
- **Modelo mais barato (Haiku) para o primeiro passe**, escalando para um
  modelo maior só quando as duas respostas do passe barato divergirem — reduz
  custo sem abrir mão da dupla checagem nos casos ambíguos.
- **Interface simples** (ex. um dashboard) para o time revisar as mensagens
  marcadas `revisar_manualmente` e corrigir com um clique, retroalimentando
  exemplos difíceis para ajuste futuro do prompt.
- **Testes de regressão do prompt**: um pequeno conjunto de mensagens "padrão
  ouro" rodado a cada mudança de prompt, para pegar regressão de qualidade
  antes de ir para produção.

## Estimativa de custo mensal (~500 mensagens/dia, Claude Sonnet 5)

Preços atuais da API (agosto/2026, sujeitos a mudança — conferir em
[docs.claude.com](https://docs.claude.com)): Sonnet 5 a US$ 2 / US$ 10 por
milhão de tokens de entrada/saída.

Por mensagem: ~2 chamadas de dupla checagem (+ ~15% das mensagens gerando uma
3ª chamada de arbitragem por divergência) → média de ~2,15 chamadas.
Cada chamada: ~600 tokens de entrada (prompt de sistema + mensagem) e ~120
tokens de saída (JSON).

```
custo por chamada ≈ (600 × 2 + 120 × 10) / 1.000.000 ≈ US$ 0,0024
custo por mensagem ≈ 2,15 × US$ 0,0024 ≈ US$ 0,0052
500 mensagens/dia × 30 dias ≈ 15.000 mensagens/mês
custo mensal ≈ 15.000 × US$ 0,0052 ≈ US$ 78/mês (≈ R$ 430–450/mês, câmbio ~R$ 5,5–5,8)
```

Com prompt caching no system prompt (fixo em toda chamada) e/ou trocando para
Haiku 4.5 (US$ 1 / US$ 5 por MTok) no primeiro passe, esse valor cai para a
faixa de **US$ 25–40/mês**. Isso não inclui infraestrutura de hospedagem
(um servidor pequeno ou uma função serverless rodando o webhook custa
tipicamente US$ 5–20/mês adicionais).

## Estrutura do projeto

```
teste-automacao-ia/
├── data/
│   ├── input/messages.json      # massa de teste do enunciado
│   ├── clients.json              # base de clientes conhecidos (bônus)
│   └── output/                   # gerado ao rodar (results.json, resumo, .db)
├── src/
│   ├── main.py                   # orquestrador / simula recebimento
│   ├── llm.py                    # prompt + chamada à API + parsing de JSON
│   ├── classifier.py             # dupla checagem + arbitragem + anti-alucinação
│   ├── schemas.py                # validação Pydantic da saída do LLM
│   ├── database.py               # SQLite
│   ├── report.py                 # resumo diário em texto
│   └── validators.py             # regex CNJ, dedup, checagem anti-alucinação
├── tests/
│   ├── test_classifier.py
│   └── test_validators.py
├── .env.example
└── requirements.txt
```

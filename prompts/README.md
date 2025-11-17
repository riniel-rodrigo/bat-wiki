# Suíte de Prompts – Documentação Modular em Lote

Esta pasta contém a suíte unificada de prompts para gerar documentação modular de processos de código-fonte em larga escala (via Batch API). Cada tópico de documentação é independente e endereçável por `custom_id`, permitindo regenerar apenas uma parte quando necessário.

## Esquema de custom_id (v2)
Use o padrão abaixo para cada item do JSONL:

```
custom_id: "doc|v1|proc=<procKey>|topic=<topic>|seg=<segIndex>|hash=<8>|lang=pt-BR|code=<code_language>"
```

- `proc`: identificador estável do processo (ex.: `venda-desconto`).
- `topic`: tópico modular (ex.: `resumo`, `fluxo_execucao`, `regras_negocio`, `diagram_activity`, `diagram_sequence`, `riscos`, `persistencia`, `interfaces_externas`).
- `seg`: índice de chunk (0 se único).
- `hash`: 8 caracteres do hash do trecho/arquivo do processo.
- `lang`: idioma da documentação final (pt-BR por padrão).
- `code`: linguagem do código analisado (java, csharp, sql, vb6, etc.).

O parser salva saídas em: `outputs/<batch_id>/docs/<proc>/<topic>.(md|puml)`.

## Placeholders padronizados
- `{{language}}`: idioma da documentação (ex.: pt-BR).
- `{{file_name}}`: nome/identificador do arquivo/processo.
- `{{code_language}}`: linguagem do código-fonte (java/csharp/sql/vb6/etc.).
- `{{content}}`: conteúdo completo do código do processo (ou chunk).
- `{{context_md}}`: documentação/arquitetura de contexto em Markdown (opcional).
- `{{methods}}`, `{{rules}}`, `{{processes}}`, `{{title}}`: dados auxiliares quando aplicável.

## Prompts desta suíte
- `00-classify.json.md`: classifica arquivo/processo (linguagem, categoria, dicas).
- `01-callgraph.json.md`: extrai call graph/linhas/definidas/externas (JSON estrito).
- `02-doc-sql.md`: documentação completa de procedures/functions SQL.
- `02-doc-general.md`: documentação macro para qualquer código.
- `03-diagram-activity.md`: diagrama de atividades (PlantUML) em linguagem de negócio.
- `03-diagram-sequence.md`: diagrama de sequência (PlantUML) em linguagem de negócio.
- `04-risk-report.md`: relatório de riscos (performance/manutenibilidade) multi-linguagem.
- `05-arch-context.json.md`: mapeia código ao documento de arquitetura (JSON).

## Exemplo de linha JSONL (resumo + diagrama)
```
{"custom_id":"doc|v1|proc=venda-desconto|topic=resumo|seg=0|hash=1a2b3c4d|lang=pt-BR|code=vb6","method":"POST","url":"/v1/chat/completions","body":{"model":"gpt-4o-mini","messages":[{"role":"user","content":"<PROMPT 02-doc-general.md com placeholders preenchidos>"}]}}
{"custom_id":"doc|v1|proc=venda-desconto|topic=diagram_activity|seg=0|hash=1a2b3c4d|lang=pt-BR|code=vb6","method":"POST","url":"/v1/chat/completions","body":{"model":"gpt-4o-mini","messages":[{"role":"user","content":"<PROMPT 03-diagram-activity.md com placeholders>"}]}}
```

## Boas práticas anti-alucinação
- Separe extração determinística (call graph, condições, consultas) da geração textual.
- Forneça apenas o trecho e artefatos necessários em cada tópico.
- Valide PlantUML e seções Markdown na pós-geraçāo.
- Use `only=[custom_id]` no parse para regerar apenas um tópico.

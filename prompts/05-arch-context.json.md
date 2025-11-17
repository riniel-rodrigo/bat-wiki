**Objetivo**
Mapear o código analisado ao documento de arquitetura/negócio fornecido (Markdown), retornando um JSON único e válido.

**Entrada**
1) Documento de Contexto (Markdown):
```
{{context_md}}
```
2) Código ({{code_language}}) – {{file_name}}:
```
{{content}}
```

**Saída (apenas JSON):**
```json
{
  "titulo": "string",
  "Arquitetura Geral": {"descricao": "string", "camadas": [{"nome": "string", "detalhes": ["string"]}]},
  "Principais Etapas Técnicas": [
    {
      "tituloEtapa": "string",
      "Métodos": ["string"],
      "Regra": {"descricaoRegra": "string", "detalhesRegra": ["string"]},
      "AcessosExternos": [{"tipo": "string", "recursos": [{"nomeRecurso": "string", "descricaoRecurso": "string"}]}],
      "Banco": ["string"],
      "Risco técnico": "string",
      "BoasPraticasEPerformance": {"Performance": ["string"], "Consistencia": ["string"], "BoasPraticas": ["string"]}
    }
  ],
  "Tabelas Envolvidas": [{"Tabela": "string", "Descrição": "string"}],
  "Serviços Externos Consumidos": {"resumo": "string", "detalhesExterno": "string"},
  "Principais Regras Técnicas": [{"tituloRegra": "string", "detalhes": ["string"]}]
}
```

**Regras**
- Extraia nomes de camadas, bullets e objetivos do documento.
- Conecte o que o código faz ao que a arquitetura descreve.
- Liste tabelas/endpoints que o código realmente usa.
- Retorne somente JSON válido.

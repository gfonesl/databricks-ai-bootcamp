# Homework 2 — Weather Intelligence

Uma Databricks App Flask que transforma alertas e previsões narrativas do National Weather Service (NWS) em documentos recuperáveis no Lakebase Postgres com pgvector.

## Arquitetura

```text
NWS alerts + forecast narratives
              |
       POST /weather/sync
              |
weather_intelligence.weather_documents
              |
 scripts/ingest_weather_embeddings.py
              |
weather_intelligence.weather_embeddings (vector(384), HNSW)
              |
      POST /weather/search
```

A geocodificação de `Chicago, IL` e `Austin, TX` usa Nominatim apenas para encontrar latitude/longitude. Os documentos recuperados — alertas e previsões — vêm exclusivamente do NWS.

## Lakebase schema

O startup da Databricks App cria o schema exclusivo `weather_intelligence`, de propriedade da service principal da App:

- `weather_documents`: documento NWS normalizado, localização, tipo (`alert`/`forecast`), texto, timestamps, payload JSONB e `content_hash` para upsert idempotente.
- `weather_embeddings`: chunks e vetores `vector(384)` do modelo `sentence-transformers/all-MiniLM-L6-v2`. A chave estrangeira `document_id` referencia `weather_documents(id)` com `ON DELETE CASCADE`.
- Índice HNSW: `idx_weather_embeddings_hnsw` usando `vector_cosine_ops` para busca por similaridade de cosseno.

O projeto Lakebase usa pgvector para a coluna `vector(384)`. Antes do primeiro deploy, uma identidade com privilégio administrativo no banco deve executar, uma única vez:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

A App não executa essa operação de nível de banco: sua service principal é proprietária apenas do schema `weather_intelligence`. Ela não guarda senhas; o `databricks-sdk` gera tokens OAuth temporários para cada nova conexão `psycopg2`.

## API

### Health

```http
GET /healthz
```

### Sincronizar documentos meteorológicos

```http
POST /weather/sync
Content-Type: application/json

{
  "locations": ["Chicago, IL", "Austin, TX"],
  "limit": 50
}
```

A resposta mantém avisos por localização quando uma fonte externa falha, sem descartar os documentos já coletados das demais localizações. O endpoint aceita até 50 documentos por chamada.

### Buscar semanticamente

```http
POST /weather/search
Content-Type: application/json

{
  "query": "flash flood risk this weekend",
  "top_k": 5
}
```

`top_k` deve estar entre 1 e 20. A resposta devolve localização, tipo, headline, trecho recuperado, data efetiva e similaridade. Antes da primeira busca, execute sync e a geração de embeddings.

## Chunking e embeddings

O script divide `headline + narrative_text` em janelas de 800 caracteres, com sobreposição de 100, tentando respeitar limites de palavras. Apenas documentos novos ou cujo `content_hash` mudou são processados; seus chunks anteriores são substituídos na mesma transação.

```bash
python scripts/ingest_weather_embeddings.py --limit 100
```

Execute o script depois do primeiro deploy da App, em compute Databricks (ou em um ambiente que receba credenciais temporárias). Ele não executa DDL: a App é a única proprietária e inicializadora do schema. Defina `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSSLMODE=require` e `LAKEBASE_ENDPOINT` somente na sessão de execução, com `DATABRICKS_CONFIG_PROFILE=BOOTCAMP` para a identidade local gerar credenciais temporárias. Use `.env.example` como lista de nomes de variáveis, nunca como local para segredos reais. A Databricks App recebe `PGHOST`, `PGDATABASE`, `PGUSER`, `PGPORT`, `PGSSLMODE` e o endpoint pelo recurso Lakebase `postgres` definido em `app.yaml` e `databricks.yml`. Em cada conexão, o `databricks-sdk` gera uma credencial OAuth temporária para a identidade da App; nenhuma senha permanente é configurada.

## Desenvolvimento e testes

```bash
python -m unittest discover -s tests -v
```

Os testes são locais e usam falsos repositórios/clientes para não exigir Lakebase, NWS ou o download do modelo.

## Deploy

Com o perfil `BOOTCAMP` configurado, no diretório desta App:

```bash
databricks bundle validate -p BOOTCAMP
databricks bundle deploy -p BOOTCAMP
databricks apps deploy day2-weather-intelligence -p BOOTCAMP
```

O comando de deploy pode variar conforme a versão do CLI; valide primeiro a sintaxe disponível em `databricks apps deploy --help`. No primeiro deploy, a service principal da App cria e passa a possuir `weather_intelligence`.

## Limitações desta versão

- NWS, Nominatim e o download inicial do modelo exigem rede externa.
- Os embeddings são gerados manualmente; um Job agendado é um próximo passo natural.
- A API oferece recuperação semântica, não uma resposta gerada por LLM.
- CDF e `REPLICA IDENTITY FULL` não são necessários: pgvector consulta diretamente o Lakebase.

## Fontes

- [National Weather Service API](https://www.weather.gov/documentation/services-web-api)
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
- [Sentence Transformers: all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
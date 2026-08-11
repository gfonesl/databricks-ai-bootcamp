# Agent validation scenarios

1. “Planeje uma viagem de três dias ao Rio de Janeiro entre 2026-08-20 e 2026-08-22, com interesse em praia e museus.”
2. “Para a viagem criada, reagende a atividade externa se houver risco de chuva e explique a evidência usada.”
3. “Gere uma lista de bagagem para a viagem e justifique cada item com a previsão armazenada.”

Expected behaviours: the agent calls tools before any weather assertion, asks for an identifier when needed, confirms every write action, and never presents a weather/safety claim as certainty.


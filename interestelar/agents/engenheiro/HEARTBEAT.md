# Heartbeat Checklist — Engenheiro de Dados

1. **Carrega padrão do repositório.** Salva caminho `repositorios/<slug>/` da empresa (está no contexto do ticket ou no vault).

2. **Lê desenho do Arquiteto + critérios de aceite do PO.** Marca cada item como checklist mental. Se algo for impossível → `REVISAO_NECESSARIA: arquiteto | Item X inviável devido Y`.

3. **Plano de implementação (5 passos):**
   1. Garante branch local (`git checkout -b feat/<id>` ou usa diretório).
   2. Escreve DDL / arquivos de tabela (respeitando `padrao-repositorio`).
   3. Escreve transformações / DAG / script de ingestão.
   4. Escreve testes / DQC.
   5. Documenta operação (comando de run, rollback).

4. **Executa passos 1-5.** Escreve as alterações no `repositorios/<slug>/`.

5. **Produz comentário de conclusão:**
   - Resumo do que foi feito
   - Lista de arquivos alterados/criados
   - Resultado de testes / runs
   - Próximos passos (se necessário)
   - `ETAPA_CONCLUIDA`
   - Se houver campo sensível não tratado → `REVISAO_NECESSARIA: governanca | Implementação contém dado X que ainda não passou por validação LGPD`

6. **Callback completed.**

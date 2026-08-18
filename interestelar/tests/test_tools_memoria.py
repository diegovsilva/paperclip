"""Fase 7 — testes do harness de revisão (SQLite): limites 3 total / 2 por par,
reset ao fechar demanda, e cache de padrão de repositório com TTL.

Cobre os casos de teste obrigatórios do roadmap:
- "Revisão cruzada com 1 ida e volta"
- "Limite de 2 idas e voltas entre mesmo par"
- "Limite de 3 revisões totais"
"""
from __future__ import annotations

from datetime import timedelta

import pytest

pytestmark = pytest.mark.asyncio


async def test_incrementar_revisao_conta_total_e_par(isolated_settings):
    from harness import tools_memoria as mem

    total, par = await mem.incrementar_revisao("ticket-1", "arquiteto", "governanca")
    assert total == 1
    assert par == 1

    state = await mem.obter_estado_revisoes("ticket-1")
    assert state.total_revisoes == 1
    assert state.par_revisoes == {"arquiteto->governanca": 1}


async def test_par_key_e_simetrico(isolated_settings):
    """Uma ida arquiteto->governanca e uma volta governanca->arquiteto contam
    para o MESMO contador de par (o protocolo é sobre o par, não a direção)."""
    from harness import tools_memoria as mem

    await mem.incrementar_revisao("ticket-2", "arquiteto", "governanca")
    total, par = await mem.incrementar_revisao("ticket-2", "governanca", "arquiteto")
    assert total == 2
    assert par == 2  # mesmo par, incrementou de novo


async def test_limite_por_par_bloqueia_na_terceira_ida_volta(isolated_settings):
    from harness import tools_memoria as mem

    await mem.incrementar_revisao("ticket-3", "arquiteto", "governanca")
    await mem.incrementar_revisao("ticket-3", "governanca", "arquiteto")
    with pytest.raises(mem.ReviewLimitError):
        await mem.incrementar_revisao("ticket-3", "arquiteto", "governanca")

    # o estado persistido não deve ter avançado além do que foi confirmado
    state = await mem.obter_estado_revisoes("ticket-3")
    assert state.total_revisoes == 2
    assert state.par_revisoes["arquiteto->governanca"] == 2


async def test_limite_total_bloqueia_na_quarta_revisao_mesmo_com_pares_diferentes(isolated_settings):
    """3 revisões totais é o teto mesmo se cada uma for com um par diferente
    (evita burlar o limite total trocando de alvo)."""
    from harness import tools_memoria as mem

    await mem.incrementar_revisao("ticket-4", "arquiteto", "governanca")
    await mem.incrementar_revisao("ticket-4", "po", "arquiteto")
    await mem.incrementar_revisao("ticket-4", "engenheiro", "analista")
    with pytest.raises(mem.ReviewLimitError):
        await mem.incrementar_revisao("ticket-4", "governanca", "analista")

    state = await mem.obter_estado_revisoes("ticket-4")
    assert state.total_revisoes == 3


async def test_resetar_revisoes_limpa_o_ticket(isolated_settings):
    from harness import tools_memoria as mem

    await mem.incrementar_revisao("ticket-5", "arquiteto", "governanca")
    await mem.resetar_revisoes("ticket-5")
    state = await mem.obter_estado_revisoes("ticket-5")
    assert state.total_revisoes == 0
    assert state.par_revisoes == {}


async def test_tickets_diferentes_tem_contadores_independentes(isolated_settings):
    from harness import tools_memoria as mem

    await mem.incrementar_revisao("ticket-A", "arquiteto", "governanca")
    await mem.incrementar_revisao("ticket-A", "arquiteto", "governanca")
    state_b = await mem.obter_estado_revisoes("ticket-B")
    assert state_b.total_revisoes == 0


async def test_salvar_e_obter_padrao_repo_com_ttl(isolated_settings):
    from harness import tools_memoria as mem

    saved = await mem.salvar_padrao_repo("acme", "# Padrão\n...", source="github_api", ttl_dias=7)
    assert not saved.is_expired()

    loaded = await mem.obter_padrao_repo("acme")
    assert loaded is not None
    assert loaded.pattern_md == "# Padrão\n..."
    assert loaded.source == "github_api"
    assert not loaded.is_expired()


async def test_padrao_repo_expirado_e_detectado(isolated_settings):
    from harness import tools_memoria as mem

    cache = await mem.salvar_padrao_repo("acme", "# X", source="manual", ttl_dias=7)
    # simula "amanhã ser depois da expiração" sem esperar 7 dias de verdade
    quase_expirado = cache.expira_em + timedelta(seconds=1)
    assert cache.is_expired(now=quase_expirado)
    assert not cache.is_expired(now=cache.obtido_em)


async def test_invalidar_padrao_repo_remove_do_cache(isolated_settings):
    from harness import tools_memoria as mem

    await mem.salvar_padrao_repo("acme", "# X", source="manual")
    await mem.invalidar_padrao_repo("acme")
    assert await mem.obter_padrao_repo("acme") is None


async def test_retorno_pendente_simples(isolated_settings):
    """arquiteto pede revisão a governanca; quando governanca conclui, o controle
    deve voltar para arquiteto — não seguir o próximo passo do #PLANO:."""
    from harness import tools_memoria as mem

    await mem.definir_retorno_pendente("ticket-r1", alvo="governanca", retornar_para="arquiteto")

    # um agente que não é o alvo esperado não deve conseguir "roubar" o retorno
    assert await mem.obter_e_limpar_retorno_pendente("ticket-r1", "engenheiro") is None

    retorno = await mem.obter_e_limpar_retorno_pendente("ticket-r1", "governanca")
    assert retorno == "arquiteto"

    # consumido uma vez, não deve reaparecer
    assert await mem.obter_e_limpar_retorno_pendente("ticket-r1", "governanca") is None


async def test_retorno_pendente_aninhado_desempilha_na_ordem_certa(isolated_settings):
    """Revisão dentro de revisão: arquiteto -> governanca -> analista.
    Analista deve voltar pra governanca; só depois governanca volta pro arquiteto."""
    from harness import tools_memoria as mem

    await mem.definir_retorno_pendente("ticket-r2", alvo="governanca", retornar_para="arquiteto")
    await mem.definir_retorno_pendente("ticket-r2", alvo="analista", retornar_para="governanca")

    # governanca ainda não pode "furar a fila" — o topo da pilha é analista
    assert await mem.obter_e_limpar_retorno_pendente("ticket-r2", "governanca") is None

    assert await mem.obter_e_limpar_retorno_pendente("ticket-r2", "analista") == "governanca"
    assert await mem.obter_e_limpar_retorno_pendente("ticket-r2", "governanca") == "arquiteto"


async def test_skill_curadoria_hash_roundtrip(isolated_settings):
    from harness import tools_memoria as mem

    h1 = mem.hash_conteudo("conteudo v1")
    await mem.registrar_proposta_skill("padrao-repositorio", h1)
    assert await mem.obter_ultimo_hash_skill_aprovado("padrao-repositorio") is None  # ainda não aprovada

    await mem.marcar_skill_aprovada("padrao-repositorio", aprovada_por="board")
    assert await mem.obter_ultimo_hash_skill_aprovado("padrao-repositorio") == h1

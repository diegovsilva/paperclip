"""Testes de parsing puro do engine_prompt: detecção de REVISAO_NECESSARIA,
ETAPA_CONCLUIDA e #PLANO na resposta do LLM. Não chama a Groq de verdade."""
from __future__ import annotations

from harness.engine_prompt import _parse_output


def test_parse_stage_complete():
    out = _parse_output("Fiz o trabalho.\n\nETAPA_CONCLUIDA\n")
    assert out.stage_complete is True
    assert out.review is None


def test_parse_revisao_necessaria():
    texto = (
        "Encontrei dados sensíveis no dicionário.\n\n"
        "REVISAO_NECESSARIA: governanca | Contém CPF, precisa checklist LGPD\n"
    )
    out = _parse_output(texto)
    assert out.review == ("governanca", "Contém CPF, precisa checklist LGPD")
    assert out.stage_complete is False


def test_parse_ignora_alvo_invalido():
    """Um slug de agente que não existe não deve virar review válido (evita
    reatribuir para um alvo inexistente)."""
    texto = "REVISAO_NECESSARIA: marketing | não faz sentido aqui\n"
    out = _parse_output(texto)
    assert out.review is None


def test_parse_plano_com_setas():
    texto = "#PLANO: PO → Arquiteto → Governanca → Engenheiro\n\nResto do texto..."
    out = _parse_output(texto)
    assert out.plan == ["po", "arquiteto", "governanca", "engenheiro"]


def test_parse_plano_com_virgulas():
    texto = "#PLANO: po, engenheiro\nETAPA_CONCLUIDA"
    out = _parse_output(texto)
    assert out.plan == ["po", "engenheiro"]
    assert out.stage_complete is True


def test_parse_sem_flags_retorna_neutro():
    out = _parse_output("Só um comentário qualquer, sem tags especiais.")
    assert out.stage_complete is False
    assert out.review is None
    assert out.plan is None


def test_parse_plano_exclui_head_mesmo_se_o_modelo_incluir():
    """Regressão de um caso real: o modelo escreveu 'HEAD' como primeiro E último passo
    do próprio plano ('#PLANO: HEAD → PO → ENGENHEIRO → HEAD (final)'), o que fazia o
    código reatribuir o ticket pro próprio Head em vez de seguir pro PO."""
    texto = "#PLANO: HEAD → PO → ENGENHEIRO → HEAD (final)\nETAPA_CONCLUIDA\n"
    out = _parse_output(texto)
    assert out.plan == ["po", "engenheiro"]
    assert "head" not in out.plan


def test_parse_review_case_insensitive_no_alvo():
    texto = "REVISAO_NECESSARIA: GOVERNANCA | motivo em maiusculo\n"
    out = _parse_output(texto)
    assert out.review == ("governanca", "motivo em maiusculo")

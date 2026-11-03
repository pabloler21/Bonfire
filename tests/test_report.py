"""Tests de eval/report.py, sin red: las cuentas de la tabla de la Fase 6 sobre filas armadas a mano."""

from eval.report import JEV_USD_PER_TOKEN, summary


def row(run, correct, labels, latency=5.0, generator_usd=0.001, jev_tokens=1000):
    return {"run": run, "correct": correct, "labels": labels, "attempts": [{}] * len(labels), "latency_s": latency,
            "generator_usd": generator_usd, "jev_tokens": jev_tokens, "models": ["gpt-5-nano", "jev-1.14.0"]}


def test_summary_counts_false_positives_over_correct_results_reviewed():
    rows = [
        row("k1", 1.0, ["pass"]),
        row("k1", 1.0, ["true_catch", "pass"]),
        row("k2", 0.0, ["missed"]),
        row("k2", 1.0, ["false_positive", "pass"], latency=20.0),
    ]
    s = summary(rows)

    assert (s["false_positives"], s["correct_reviewed"]) == (1, 4)  # un FP sobre cuatro resultados correctos revisados
    assert (s["true_catches"], s["wrong_reviewed"]) == (1, 2)
    assert (s["accuracy_min"], s["accuracy_max"], s["accuracy_mean"]) == (0.5, 1.0, 0.75)  # por corrida
    assert s["attempts_max"] == 2
    assert summary([*rows, {"run": "k2", "error": "Error: 401"}])["errors"] == 1  # un error no entra en las métricas
    assert s["cost_usd_mean"] == 0.001 + 1000 * JEV_USD_PER_TOKEN

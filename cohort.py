"""
cohort.py
---------
Análise de cohort de retenção por fase (Espera, CNPJ, IM, CRM).

Cohort: dos cards que ENTRARAM numa fase durante uma semana,
quantos permaneceram após 3, 6, 9, 12, 15, 21 dias úteis.

Usa as colunas de data de entrada por etapa da tabela_completa:
  - Espera : coluna com data de entrada na etapa 0 ou 1
  - CNPJ   : coluna com data de entrada na etapa 2
  - IM     : coluna com data de entrada na etapa 12
  - CRM    : coluna com data de entrada na etapa 17
"""

import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

COHORT_PATH = "cohort_snapshots.json"
INTERVALS   = [3, 6, 9, 12, 15, 21]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _find_col(df, patterns):
    """Encontra a primeira coluna que bate com qualquer padrão regex."""
    for pat in patterns:
        for col in df.columns:
            if re.search(pat, _norm(col)):
                return col
    return None


def _parse_date(raw):
    """Converte string de data para date, ou None se inválida."""
    import pandas as pd
    if raw is None or (hasattr(raw, '__class__') and raw.__class__.__name__ == 'float'):
        return None
    try:
        import pandas as pd
        if pd.isna(raw):
            return None
    except Exception:
        pass
    try:
        s = str(raw).split("T")[0].split(" ")[0].strip()
        return date.fromisoformat(s)
    except Exception:
        return None


def _add_bdays(start, n):
    """Avança n dias úteis a partir de start."""
    d, added = start, 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def _iso_week(d):
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _week_range(d):
    mon = d - timedelta(days=d.weekday())
    fri = mon + timedelta(days=4)
    return f"{mon.strftime('%d/%m')} – {fri.strftime('%d/%m')}"


# ── Detecção de colunas ───────────────────────────────────────────────────────

# Padrões para detectar as colunas de data de entrada em cada fase.
# O usuário confirmou: entrada CNPJ = "entrada 2 CNPJ", IM = "etapa 12", CRM = "etapa 17".
COL_PATTERNS = {
    "cpf":    [r"cpf", r"chave", r"documento", r"id.?card"],
    "etapa":  [r"etapa.?atual.?numero", r"etapa.?atual", r"etapa"],
    "Espera": [r"espera", r"etapa.?0", r"etapa.?1\b", r"inicio", r"abertura", r"criacao"],
    "CNPJ":   [r"cnpj", r"etapa.?2\b", r"entrada.?2"],
    "IM":     [r"etapa.?12\b", r"im\b", r"entrada.?im"],
    "CRM":    [r"etapa.?17\b", r"crm\b", r"entrada.?crm"],
}

# Para cada fase, qual coluna de data indica a SAÍDA (= entrada na fase seguinte)
PHASE_EXIT = {
    "Espera": "CNPJ",
    "CNPJ":   "IM",
    "IM":     "CRM",
    "CRM":    None,   # não temos dado de saída do CRM
}


def detect_date_columns(df):
    """
    Detecta as colunas de data de entrada para cada fase.
    Retorna dict {fase: col_name} e imprime aviso para colunas não encontradas.
    """
    date_cols = {}
    for phase in ["Espera", "CNPJ", "IM", "CRM"]:
        col = _find_col(df, COL_PATTERNS[phase])
        date_cols[phase] = col
        if not col:
            print(f"    AVISO cohort: coluna de data para '{phase}' não encontrada.")

    # Debug: mostra colunas disponíveis caso alguma não seja encontrada
    if any(v is None for v in date_cols.values()):
        print(f"    Colunas disponíveis: {list(df.columns)}")

    return date_cols


# ── Extração do snapshot de cards ─────────────────────────────────────────────

def extract_card_snapshot(df):
    """
    Extrai lista de cards com suas datas de entrada por fase.
    Retorna lista de dicts: {cpf, etapa_cat, date_Espera, date_CNPJ, date_IM, date_CRM}
    """
    import pandas as pd

    col_cpf   = _find_col(df, COL_PATTERNS["cpf"])
    col_etapa = _find_col(df, COL_PATTERNS["etapa"])
    date_cols = detect_date_columns(df)

    if not col_cpf:
        print("    AVISO: coluna CPF não encontrada — snapshot não salvo.")
        return []

    cards = []
    for _, row in df.iterrows():
        cpf = str(row.get(col_cpf, "")).strip()
        if not cpf or cpf == "nan":
            continue

        entry = {"cpf": cpf}

        # etapa atual
        if col_etapa:
            try:
                entry["etapa_num"] = int(row[col_etapa])
            except (ValueError, TypeError):
                entry["etapa_num"] = None

        # datas de entrada em cada fase
        for phase, col in date_cols.items():
            entry[f"data_{phase}"] = _parse_date(row.get(col)) if col else None

        cards.append(entry)

    return cards


# ── Persistência ──────────────────────────────────────────────────────────────

def save_cohort_snapshot(cards, path=COHORT_PATH):
    """Salva/atualiza o snapshot de hoje em cohort_snapshots.json."""
    snapshots = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            snapshots = json.load(f)

    today = date.today().isoformat()

    # Serializa datas
    def serial(c):
        out = {"cpf": c["cpf"]}
        for k, v in c.items():
            if k == "cpf":
                continue
            out[k] = v.isoformat() if isinstance(v, date) else v
        return out

    snapshots = [s for s in snapshots if s["data"] != today]
    snapshots.append({"data": today, "cards": [serial(c) for c in cards]})
    snapshots.sort(key=lambda s: s["data"])

    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, indent=2, ensure_ascii=False)

    return snapshots


def load_cohort_snapshots(path=COHORT_PATH):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Cálculo de cohort ─────────────────────────────────────────────────────────

def compute_cohorts(cards, intervals=None, today=None):
    """
    Calcula tabelas de cohort a partir da lista de cards extraída da tabela_completa.

    Usa as datas de entrada por fase (data_CNPJ, data_IM, etc.) para determinar:
      - Quando o card entrou na fase (= cohort de entrada)
      - Quando saiu (= entrada na fase seguinte)
      - Se permaneceu X dias úteis na fase

    Retorna:
      {fase: {week_label: {
          'range': 'DD/MM – DD/MM',
          'initial': N,
          'intervals': {3: {'survived': n, 'denominator': m}, ...}
      }}}
    """
    if intervals is None:
        intervals = INTERVALS
    if today is None:
        today = date.today()

    result = {}

    for phase in ["Espera", "CNPJ", "IM", "CRM"]:
        exit_phase = PHASE_EXIT[phase]
        cohort_weeks = defaultdict(list)  # week_label → [card_info]

        for card in cards:
            entry_raw = card.get(f"data_{phase}")
            if entry_raw is None:
                continue
            entry_date = _parse_date(entry_raw) if isinstance(entry_raw, str) else entry_raw
            if not entry_date:
                continue

            # Data de saída = entrada na fase seguinte (None = ainda na fase)
            exit_date = None
            if exit_phase:
                exit_raw = card.get(f"data_{exit_phase}")
                exit_date = _parse_date(exit_raw) if isinstance(exit_raw, str) else exit_raw

            week = _iso_week(entry_date)
            cohort_weeks[week].append({
                "entry_date": entry_date,
                "exit_date": exit_date,
            })

        if not cohort_weeks:
            continue

        result[phase] = {}
        for week_label, members in sorted(cohort_weeks.items()):
            n = len(members)
            interval_counts = {}

            for interval in intervals:
                survived    = 0
                denominator = 0

                for m in members:
                    target = _add_bdays(m["entry_date"], interval)

                    if today < target:
                        continue  # Ainda não chegou o dia I para este card

                    denominator += 1

                    # Permaneceu: saiu depois do dia I, ou ainda não saiu
                    if m["exit_date"] is None or m["exit_date"] >= target:
                        survived += 1

                interval_counts[interval] = {
                    "survived":    survived,
                    "denominator": denominator,  # cards para os quais o dia I já passou
                }

            first_entry = min(m["entry_date"] for m in members)
            result[phase][week_label] = {
                "range":     _week_range(first_entry),
                "initial":   n,
                "intervals": interval_counts,
            }

    return result


# ── Formatação Markdown ───────────────────────────────────────────────────────

def build_cohort_markdown(cohort_tables, phase, intervals=None):
    """Gera tabela Markdown para exibição no Metabase."""
    if intervals is None:
        intervals = INTERVALS

    data = cohort_tables.get(phase, {})
    if not data:
        return (
            f"## Cohort {phase}\n\n"
            "_Sem dados de entrada para esta fase._"
        )

    header = "| Semana |  N  |" + "".join(f" Dia {i} |" for i in intervals)
    sep    = "|---|:---:|" + "".join(":---:|" for _ in intervals)
    rows   = []

    for wk in sorted(data.keys(), reverse=True):
        d = data[wk]
        n = d["initial"]
        row = f"| {d['range']} | {n} |"
        for i in intervals:
            v = d["intervals"].get(i, {})
            denom = v.get("denominator", 0)
            surv  = v.get("survived", 0)
            if denom == 0:
                row += " — |"
            else:
                pct = f"{surv / denom * 100:.0f}%"
                row += f" {surv} ({pct}) |"
        rows.append(row)

    return f"## Cohort {phase}\n\n{header}\n{sep}\n" + "\n".join(rows)

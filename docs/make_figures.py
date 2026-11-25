"""Будує рисунки для пояснювальної записки з файлів у results/.

    .venv/bin/python docs/make_figures.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = ROOT / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "DejaVu Serif",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
})
INK = "#1f2933"
BLUE = "#2f6db5"
ORANGE = "#d9822b"
GREY = "#9aa5b1"
LINE_RE = re.compile(r"^\S+ (\d\d):(\d\d):(\d\d),\d+ .*received=(\d+).*\| (\d+) msg/s in")


def box(ax, x, y, w, h, text, fc="#ffffff", ec=INK, fs=10, bold=False):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fc, ec=ec, lw=1.2))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=INK,
            fontweight="bold" if bold else "normal", wrap=True)


def diamond(ax, x, y, w, h, text, fs=9):
    ax.add_patch(Polygon([(x, y + h / 2), (x + w / 2, y), (x, y - h / 2), (x - w / 2, y)],
                         closed=True, fc="#ffffff", ec=INK, lw=1.2))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=INK)


def arrow(ax, x1, y1, x2, y2, text="", color=INK, ls="-", text_offset=(0.0, 0.12)):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=12,
                                 color=color, lw=1.2, linestyle=ls))
    if text:
        ax.text((x1 + x2) / 2 + text_offset[0], (y1 + y2) / 2 + text_offset[1], text,
                ha="center", va="bottom", fontsize=8.5, color=color)


def fig_architecture():
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    box(ax, 1.2, 3.6, 2.0, 0.9, "ESP32 +\nPZEM-004T v3.0\n(вузли обліку)")
    box(ax, 1.2, 1.8, 2.0, 0.9, "Емулятор\nлічильників\n(частина 1.3)", fc="#f4f6f8")
    box(ax, 3.9, 2.7, 1.7, 1.0, "Mosquitto\nMQTT-брокер")
    box(ax, 6.3, 2.7, 2.0, 1.25, "Колектор\nPython 3.12\n(частина 1.2)\nкопії 1…N", fc="#e8f0fa", ec=BLUE, bold=True)
    box(ax, 6.3, 0.75, 2.0, 0.7, "config/meters.json\nдовідник лічильників", fs=9, fc="#f4f6f8")
    box(ax, 8.85, 2.7, 1.9, 1.0, "InfluxDB 2.7\nbucket meters")
    box(ax, 8.85, 4.15, 1.9, 0.6, "Grafana (1.5)", fs=9.5, fc="#f4f6f8")
    box(ax, 8.85, 1.15, 1.9, 0.75, "Обробка (1.4)\nNode-RED, API", fs=9.5, fc="#f4f6f8")
    arrow(ax, 2.2, 3.45, 3.05, 2.95, "JSON, Wi-Fi", text_offset=(0.25, 0.2))
    arrow(ax, 2.2, 1.95, 3.05, 2.45, "JSON", text_offset=(-0.15, -0.05))
    arrow(ax, 4.75, 2.7, 5.3, 2.7)
    ax.text(5.02, 3.4, "$share,\nQoS 1", ha="center", va="bottom", fontsize=8.5, color=INK)
    arrow(ax, 7.3, 2.7, 7.9, 2.7)
    ax.text(7.6, 3.4, "пачки\nline protocol", ha="center", va="bottom", fontsize=8.5, color=INK)
    arrow(ax, 6.3, 1.1, 6.3, 2.07)
    arrow(ax, 8.85, 3.2, 8.85, 3.85, color=GREY)
    arrow(ax, 8.85, 2.2, 8.85, 1.52, color=GREY)
    ax.text(3.9, 1.95, "топік meters/<район>/<лічильник>/readings", ha="center", va="top", fontsize=8.5,
            color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "fig_architecture.png", dpi=200)
    plt.close(fig)


def fig_algorithm():
    fig, ax = plt.subplots(figsize=(8.6, 12.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(-1.2, 13.2)
    ax.axis("off")
    x = 4.0
    box(ax, x, 12.75, 3.6, 0.55, "Початок", fs=10)
    box(ax, x, 11.95, 5.0, 0.7, "Завантажити довідник лічильників.\nВідновити стан лічильників з InfluxDB", fs=9)
    box(ax, x, 11.1, 4.6, 0.55, "Підписатися на meters/+/+/readings", fs=9)
    box(ax, x, 10.35, 3.6, 0.55, "Отримати повідомлення", fs=9)
    checks = [
        "JSON\nкоректний?", "Поля і типи\nправильні?", "Номер у топіку\nзбігається?",
        "Лічильник\nу довіднику?", "Значення в\nдіапазонах?", "P ≤ U·I·фази\n·1,1 + 10?",
        "Час не з майбут-\nнього й не старий?", "Час і енергія\nне зменшились?",
    ]
    y = 9.45
    ys = []
    for text in checks:
        diamond(ax, x, y, 2.9, 0.82, text, fs=8)
        ys.append(y)
        y -= 1.0
    arrow(ax, x, 12.47, x, 12.3)
    arrow(ax, x, 11.6, x, 11.38)
    arrow(ax, x, 10.82, x, 10.63)
    arrow(ax, x, 10.07, x, ys[0] + 0.41)
    for a, b in zip(ys, ys[1:]):
        arrow(ax, x, a - 0.41, x, b + 0.41)
        ax.text(x + 0.12, (a + b) / 2 - 0.05, "так", fontsize=8, color=INK)
    # гілка відмови
    rx = 8.0
    box(ax, rx, (ys[0] + ys[-1]) / 2, 3.0, 1.1, "Записати в буфер\nrejected_messages\nз кодом причини", fs=9,
        fc="#fdf1e6", ec=ORANGE)
    for yy in ys:
        ax.plot([x + 1.45, rx - 1.55], [yy, yy], color=ORANGE, lw=1.0)
        ax.text(x + 1.6, yy + 0.05, "ні", fontsize=8, color=ORANGE)
    ax.plot([rx - 1.55, rx - 1.55], [ys[0], ys[-1]], color=ORANGE, lw=1.0)
    yacc = ys[-1] - 1.05
    box(ax, x, yacc, 4.4, 0.7, "Записати в буфер readings.\nОновити стан лічильника", fs=9, fc="#e8f0fa", ec=BLUE)
    arrow(ax, x, ys[-1] - 0.41, x, yacc + 0.35)
    ax.text(x + 0.12, ys[-1] - 0.58, "так", fontsize=8, color=INK)
    yflush = yacc - 1.05
    diamond(ax, x, yflush, 3.2, 0.85, "У буфері ≥ 1000 точок\nабо минула 1 с?", fs=8)
    arrow(ax, x, yacc - 0.35, x, yflush + 0.43)
    ax.add_patch(FancyArrowPatch((rx, (ys[0] + ys[-1]) / 2 - 0.55), (x + 1.6, yflush), arrowstyle="-|>",
                                 mutation_scale=12, color=ORANGE, lw=1.0, connectionstyle="angle,angleA=-90,angleB=0"))
    ywrite = yflush - 1.05
    box(ax, x, ywrite, 4.2, 0.6, "Записати пачку в InfluxDB", fs=9)
    arrow(ax, x, yflush - 0.43, x, ywrite + 0.3)
    ax.text(x + 0.12, yflush - 0.62, "так", fontsize=8, color=INK)
    # повернення до отримання
    lx = 0.7
    ax.plot([x - 1.6, lx], [yflush, yflush], color=INK, lw=1.0)
    ax.text(x - 1.85, yflush + 0.05, "ні", fontsize=8, color=INK)
    ax.plot([x - 2.1, lx], [ywrite, ywrite], color=INK, lw=1.0)
    ax.plot([lx, lx], [ywrite, 10.35], color=INK, lw=1.0)
    arrow(ax, lx, 10.35, x - 1.8, 10.35)
    fig.tight_layout()
    fig.savefig(OUT / "fig_algorithm.png", dpi=200)
    plt.close(fig)


def read_rates(path: Path) -> tuple[list[float], list[int], list[int]]:
    t, rec, rate = [], [], []
    t0 = None
    for line in path.read_text().splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        hh, mm, ss, received, r = map(int, m.groups())
        sec = hh * 3600 + mm * 60 + ss
        if t0 is None:
            if r == 0:
                continue
            t0 = sec - 1
        t.append(sec - t0)
        rec.append(received)
        rate.append(r)
    return t, rec, rate


def fig_load(publish_end_s: float = 56.1):
    t, rec, rate = read_rates(RES / "load4_collector.log")
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(t, rate, color=BLUE, lw=1.4, label="швидкість обробки колектором")
    ax.axvline(publish_end_s, color=ORANGE, ls="--", lw=1.2)
    ax.text(publish_end_s + 1, max(rate) * 0.93, "емулятори\nзавершили\nпублікацію", color=ORANGE, fontsize=9,
            va="top")
    ax2 = ax.twinx()
    ax2.plot(t, [r / 1000 for r in rec], color=GREY, lw=1.2, ls="-.", label="отримано всього, тис.")
    ax2.set_ylabel("отримано всього, тис. повідомлень", color="#52606d")
    ax2.spines["top"].set_visible(False)
    ax.set_xlabel("час від початку тесту, с")
    ax.set_ylabel("повідомлень за секунду")
    ax.set_xlim(0, max(t) + 2)
    ax.set_ylim(0)
    ax2.set_ylim(0, 420)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "fig_load.png", dpi=200)
    plt.close(fig)


def fig_steps():
    def rows(name):
        with open(RES / name) as fh:
            return list(csv.DictReader(fh))

    series = [
        ("1 копія, прогін 1", rows("step_test_x1_run1.csv"), "#9fb7d9", "o"),
        ("1 копія, прогін 2", rows("step_test_x1_run2.csv"), BLUE, "s"),
        ("2 копії", rows("step_test_x2.csv"), ORANGE, "^"),
    ]
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    lim = 6500
    ax.plot([0, lim], [0, lim], color=GREY, lw=1, ls=":", label="ідеал, усе отримано вчасно")
    for label, data, color, marker in series:
        xs = [int(r["rate_target"]) for r in data]
        ys = [int(r["rate_collected"]) for r in data]
        ax.plot(xs, ys, marker=marker, color=color, lw=1.4, label=label)
    ax.set_xlabel("задана сумарна швидкість емуляторів, повідомлень/с")
    ax.set_ylabel("отримано колектором за час\nпублікації, повідомлень/с")
    ax.set_xlim(500, lim)
    ax.set_ylim(0, lim)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "fig_steps.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    fig_architecture()
    fig_algorithm()
    fig_load()
    fig_steps()
    print("figures in", OUT)

from __future__ import annotations

from cycler import cycler
import matplotlib.pyplot as plt
import seaborn as sns

PLOT_PALETTE = [
    "#4C78A8",  # muted blue (primary)
    "#F58518",  # orange (accent)
    "#54A24B",
    "#E45756",
    "#72B7B2",
    "#EECA3B",
]

PRIMARY_COLOR = PLOT_PALETTE[0]
ACCENT_COLOR = PLOT_PALETTE[1]


def apply_plot_style(
    *,
    style: str = "white",
    axes_grid: bool = False,
    font_size: int = 12,
    title_size: int = 14,
    label_size: int = 12,
    tick_size: int = 10,
    legend_size: int = 10,
) -> None:
    """
    Apply shared plotting theme across notebooks.

    Grid: default is no grid (`axes_grid=False`). Seaborn themes like `darkgrid`
    and `whitegrid` are drawn with grid in mind; pass `axes_grid=False` (default)
    to turn grid off even when using those style names. For a clean plot with no
    grid, prefer `style="white"` or `style="ticks"` and the default `axes_grid`.
    """
    sns.set_theme(
        style=style,
        palette=PLOT_PALETTE,
        rc={"axes.grid": axes_grid},
    )

    plt.rcParams.update(
        {
            "axes.facecolor": "#EAEAF2",
            "figure.facecolor": "white",
            "axes.grid": axes_grid,
            "axes.prop_cycle": cycler(color=PLOT_PALETTE),
            "font.size": font_size,
            "axes.titlesize": title_size,
            "axes.labelsize": label_size,
            "xtick.labelsize": tick_size,
            "ytick.labelsize": tick_size,
            "legend.fontsize": legend_size,
            "legend.title_fontsize": legend_size,
        }
    )

